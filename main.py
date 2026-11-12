import os
import re
import json
import base64
import shutil
import inspect
import asyncio
import urllib.parse
from datetime import datetime
import requests
import pandas as pd
import flet as ft
from dependencias import *


class RecepcionModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list, get_indice_activo):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables
        self.get_indice_activo = get_indice_activo

        # --- 1. CONSTANTES Y FUNCIONES AUXILIARES DE DISEÑO OSCURO ---
        BG_MODULO = "#1B2122"
        BG_CARD = "#262E30"
        BG_INPUT = "#1D2426"
        BG_DIGITAL = "#121718"
        BORDER_COLOR = "#3B484B"
        ACCENT_TEAL = "#527976"
        ACCENT_CYAN = "#38BDF8"
        ACCENT_BLUE = "#0284C7"
        TEXT_WHITE = "#FFFFFF"
        TEXT_MUTED = "#94A3B8"

        # --- HELPERS DE AISLAMIENTO MULTI-BODEGA CON RESPALDO SEGURO ---
        def obtener_bodega_actual() -> str:
            bod = str(getattr(self.page, "bodega_actual", "") or "").strip()
            return bod if bod in ("Bodega Santiago", "Bodega Concepcion") else "Bodega Santiago"

        def coincide_bodega_fila(fila: dict, bodega_objetivo: str = None) -> bool:
            if not isinstance(fila, dict):
                return False
            bod_obj = (bodega_objetivo or obtener_bodega_actual()).strip()
            bod_fila = str(fila.get("bodega") or "").strip()
            if not bod_fila or bod_fila.upper() in ("NONE", "NULL"):
                return bod_obj.upper() == "BODEGA SANTIAGO"
            return bod_fila.upper() == bod_obj.upper()

        def notificar(texto: str, color: str = "#0284C7"):
            from dependencias import notificar_global
            notificar_global(self.page, texto, color)

        def mostrar_aviso_ingreso_modal(lpn_str, sku_str, unid_str, lote_str, qa_str):
            from dependencias import mostrar_aviso_ingreso_modal_global
            mostrar_aviso_ingreso_modal_global(self.page, lpn_str, sku_str, unid_str, lote_str, qa_str)

        def _nombre_archivo_seguro_local(texto: str) -> str:
            limpio = "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in str(texto or ""))
            while "__" in limpio:
                limpio = limpio.replace("__", "_")
            return limpio.strip("_")[:45] or "DOC"

        def _txt_latin(texto) -> str:
            s = str(texto or "").replace("•", "-").replace("—", "-").replace("–", "-")
            return s.encode("latin-1", "replace").decode("latin-1")

        def _buscar_ruta_logo_ludipek():
            raiz_proy = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            posibles = [
                os.path.join(os.getcwd(), "assets", "logo.png"),
                os.path.join(os.getcwd(), "logo.png"),
                os.path.join(raiz_proy, "assets", "logo.png"),
                os.path.join(raiz_proy, "logo.png"),
                obtener_ruta_recurso("logo.png"),
                obtener_ruta_recurso(os.path.join("assets", "logo.png")),
            ]
            return next((p for p in posibles if p and os.path.exists(p)), None)

        def consultar_maestra_por_skus(skus_requeridos: set = None) -> tuple[dict, dict]:
            """Obtiene descripciones y múltiplos desde maestra_sku sin truncarse en 1.000 registros."""
            mapa_desc = {}
            mapa_mult = {}
            try:
                lista_limpia = [s.strip().upper() for s in (skus_requeridos or set()) if s and str(s).strip()]
                filas_m = []
                if lista_limpia and len(lista_limpia) <= 150:
                    res_m = supabase.table("maestra_sku").select("sku, descripcion, multiplo").in_("sku", lista_limpia).execute()
                    filas_m = res_m.data or []
                else:
                    paso = 1000
                    for off in range(0, 4000, paso):
                        res_m = supabase.table("maestra_sku").select("sku, descripcion, multiplo").range(off, off + paso - 1).execute()
                        lote = res_m.data or []
                        filas_m.extend(lote)
                        if len(lote) < paso:
                            break

                for r in filas_m:
                    s_k = str(r.get("sku") or "").strip().upper()
                    if not s_k:
                        continue
                    if r.get("descripcion"):
                        mapa_desc[s_k] = str(r.get("descripcion") or "").strip()
                    try:
                        mult_v = max(1, int(float(r.get("multiplo") or 1)))
                        if mult_v > mapa_mult.get(s_k, 1):
                            mapa_mult[s_k] = mult_v
                    except Exception:
                        pass
            except Exception:
                pass
            return mapa_desc, mapa_mult

        def descargar_archivo_web(ruta_archivo: str, titulo_doc: str = "Documento Generado"):
            """Abre el archivo en Windows local (os.startfile) y publica enlace directo en SnackBar para Web sin usar page.launch_url."""
            if not ruta_archivo or not os.path.exists(ruta_archivo):
                notificar("No se encontró el archivo generado en el servidor.", "#B91C1C")
                return
            try:
                descargar_o_abrir_archivo(self.page, ruta_archivo)
            except Exception as ex_dl:
                notificar(f"Error preparando descarga ({titulo_doc}): {ex_dl}", "#B91C1C")

        def generar_acta_pdf_completa(cabecera_po: dict, filas_conc: list, recepciones_lpn: list) -> str:
            """Genera el Acta Oficial PDF A4 con Logo Ludipek alineado, sin tabla de LPNs y con alerta de Sobrantes / Fuera de OC."""
            from fpdf import FPDF

            os.makedirs("reportes_recepcion", exist_ok=True)
            codigo_po = str(cabecera_po.get("codigo_asn") or "S/OC").strip()
            proveedor = str(cabecera_po.get("proveedor") or "RECEPCION DIRECTA").strip()
            oc_raw = str(cabecera_po.get("numero_oc") or "").strip()
            oc_num = codigo_po if oc_raw.upper() in ("", "S/OC", "S/N", "NONE") else oc_raw
            estado_po = str(cabecera_po.get("estado") or "EN_RECEPCION").strip()
            contenedor_guia = str(cabecera_po.get("contenedor_referencia") or "N/A").strip()
            ahora_str = datetime.now().strftime("%d-%m-%Y %H:%M")

            pdf = FPDF(orientation="P", unit="mm", format="A4")
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()

            # --- ENCABEZADO CORPORATIVO CON LOGO LUDIPEK PERFECTAMENTE ENCUADRADO ---
            pdf.set_fill_color(15, 23, 42)
            pdf.rect(0, 0, 210, 30, style="F")

            ruta_logo = _buscar_ruta_logo_ludipek()
            x_texto = 10
            if ruta_logo:
                try:
                    pdf.set_fill_color(255, 255, 255)
                    pdf.rect(10, 3, 24, 24, style="F")
                    pdf.image(ruta_logo, x=11, y=4, w=22, h=22)
                    x_texto = 39
                except Exception:
                    x_texto = 10

            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_xy(x_texto, 6)
            pdf.cell(200 - x_texto, 6, txt=_txt_latin(f"LUDIPEK WMS - ACTA OFICIAL DE RECEPCION (OC: {oc_num})"), ln=True)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_x(x_texto)
            pdf.cell(200 - x_texto, 5.5, txt=_txt_latin(f"Proveedor: {proveedor[:48]}   |   Fecha Emision: {ahora_str}"), ln=True)
            pdf.set_x(x_texto)
            pdf.cell(200 - x_texto, 5.5, txt=_txt_latin(f"Referencia / Nota: {codigo_po[:38]}   |   Contenedor: {contenedor_guia}   |   Estado: {estado_po}"), ln=True)
            pdf.set_text_color(0, 0, 0)

            # --- BLOQUE RESUMEN DE CABECERA ---
            pdf.set_xy(10, 35)
            pdf.set_fill_color(241, 245, 249)
            pdf.set_draw_color(203, 213, 225)
            pdf.rect(10, 35, 190, 16, style="DF")
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_xy(14, 37.5)
            pdf.cell(92, 5, txt=_txt_latin(f"ORDEN DE COMPRA: {oc_num}"[:44]))
            pdf.cell(92, 5, txt=_txt_latin(f"PROVEEDOR: {proveedor}"[:44]), ln=True)
            pdf.set_x(14)
            pdf.cell(92, 5, txt=_txt_latin(f"NOTA / PO: {codigo_po}"[:44]))
            pdf.cell(92, 5, txt=_txt_latin(f"CONTENEDOR / GUIA: {contenedor_guia}"[:44]), ln=True)

            # --- TABLA ÚNICA: DETALLE POR SKU, LOTE, VENCIMIENTO Y ESTATUS DE CONCILIACIÓN ---
            pdf.set_xy(10, 55)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(190, 6, txt="DETALLE DE RECEPCION POR SKU, LOTE, VENCIMIENTO Y CONCILIACION OC", ln=True)

            mapa_conc_sku = {}
            for f in filas_conc:
                s_k = str(f.get("sku") or "").strip().upper()
                if s_k:
                    mapa_conc_sku[s_k] = f

            lotes_agrupados = {}
            for r in recepciones_lpn:
                s_r = str(r.get("sku") or "").strip().upper()
                if not s_r:
                    continue
                lote_limpio, _ = extraer_estado_qa(r.get("lote", "S/L"))
                venc_r = str(r.get("fecha_vencimiento_cl") or "S/F").strip()
                cajas_r = int(r.get("cajas") or 0)
                unid_r = int(r.get("unidades_totales") or 0)
                clave = (s_r, lote_limpio, venc_r)
                if clave not in lotes_agrupados:
                    lotes_agrupados[clave] = {"cajas": 0, "unidades": 0}
                lotes_agrupados[clave]["cajas"] += cajas_r
                lotes_agrupados[clave]["unidades"] += unid_r

            pdf.set_fill_color(30, 58, 138)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(24, 7, "SKU", border=1, fill=True)
            pdf.cell(62, 7, "DESCRIPCION", border=1, fill=True)
            pdf.cell(26, 7, "LOTE", border=1, align="C", fill=True)
            pdf.cell(22, 7, "VENCIMIENTO", border=1, align="C", fill=True)
            pdf.cell(14, 7, "CAJAS", border=1, align="C", fill=True)
            pdf.cell(16, 7, "UNID.", border=1, align="C", fill=True)
            pdf.cell(26, 7, "ESTATUS OC", border=1, align="C", fill=True, ln=True)

            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 7.8)
            tot_cajas_acta = 0
            tot_unid_acta = 0
            incidencias_acta = []

            for (sku_k, lote_k, venc_k), inf_l in sorted(lotes_agrupados.items()):
                info_c = mapa_conc_sku.get(sku_k, {})
                desc_k = str(info_c.get("descripcion") or "Ingreso Recepcion")
                est_sku = str(info_c.get("estado") or "VALIDADA")
                dif_cajas_sku = int(info_c.get("dif_cajas") or 0)

                if est_sku == "SKU FUERA DE OC":
                    txt_est_pdf = "FUERA DE OC"
                elif est_sku == "SOBRANTE":
                    txt_est_pdf = f"SOBRANTE ({dif_cajas_sku:+d} Cj)"
                elif est_sku == "PARCIAL":
                    txt_est_pdf = f"PARCIAL ({dif_cajas_sku:+d} Cj)"
                else:
                    txt_est_pdf = "OK (VALIDADA)"

                tot_cajas_acta += inf_l["cajas"]
                tot_unid_acta += inf_l["unidades"]

                es_alerta = est_sku in ("SKU FUERA DE OC", "SOBRANTE")
                if es_alerta:
                    pdf.set_fill_color(254, 226, 226)
                else:
                    pdf.set_fill_color(255, 255, 255)

                pdf.cell(24, 5.8, _txt_latin(sku_k)[:13], border=1, fill=es_alerta)
                pdf.cell(62, 5.8, _txt_latin(desc_k)[:35], border=1, fill=es_alerta)
                pdf.cell(26, 5.8, _txt_latin(lote_k)[:14], border=1, align="C", fill=es_alerta)
                pdf.cell(22, 5.8, _txt_latin(venc_k)[:11], border=1, align="C", fill=es_alerta)
                pdf.cell(14, 5.8, str(inf_l["cajas"]), border=1, align="C", fill=es_alerta)
                pdf.cell(16, 5.8, str(inf_l["unidades"]), border=1, align="C", fill=es_alerta)
                pdf.cell(26, 5.8, _txt_latin(txt_est_pdf)[:15], border=1, align="C", fill=es_alerta, ln=True)

            if not lotes_agrupados and filas_conc:
                for f in filas_conc:
                    s_f = str(f.get("sku") or "").strip().upper()
                    c_rec = int(f.get("cajas_recibidas") or 0)
                    u_rec = int(f.get("unidades_recibidas") or 0)
                    tot_cajas_acta += c_rec
                    tot_unid_acta += u_rec
                    pdf.cell(24, 5.8, _txt_latin(s_f)[:13], border=1)
                    pdf.cell(62, 5.8, _txt_latin(f.get("descripcion", ""))[:35], border=1)
                    pdf.cell(26, 5.8, _txt_latin(f.get("lotes_reales", "SIN INGRESO"))[:14], border=1, align="C")
                    pdf.cell(22, 5.8, "-", border=1, align="C")
                    pdf.cell(14, 5.8, str(c_rec), border=1, align="C")
                    pdf.cell(16, 5.8, str(u_rec), border=1, align="C")
                    pdf.cell(26, 5.8, _txt_latin(f.get("estado", "PENDIENTE"))[:14], border=1, align="C", ln=True)

            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_fill_color(226, 232, 240)
            pdf.cell(134, 6.5, "TOTAL FISICO RECIBIDO", border=1, align="R", fill=True)
            pdf.cell(14, 6.5, str(tot_cajas_acta), border=1, align="C", fill=True)
            pdf.cell(16, 6.5, str(tot_unid_acta), border=1, align="C", fill=True)
            pdf.cell(26, 6.5, "", border=1, align="C", fill=True, ln=True)

            for f in filas_conc:
                est_f = str(f.get("estado") or "")
                if est_f in ("SKU FUERA DE OC", "SOBRANTE", "PARCIAL"):
                    s_f = f.get("sku")
                    c_esp = int(f.get("cajas_esperadas") or 0)
                    c_rec = int(f.get("cajas_recibidas") or 0)
                    u_esp = int(f.get("unidades_esperadas") or 0)
                    u_rec = int(f.get("unidades_recibidas") or 0)
                    dif_c = c_rec - c_esp
                    dif_u = u_rec - u_esp
                    incidencias_acta.append(
                        f"- {s_f} [{est_f}]: OC Esperado {c_esp} Cj ({u_esp} UN) vs Recibido {c_rec} Cj ({u_rec} UN) -> Dif: {dif_c:+d} Cj ({dif_u:+d} UN)"
                    )

            if incidencias_acta:
                pdf.ln(4)
                pdf.set_font("Helvetica", "B", 8.5)
                pdf.set_text_color(185, 28, 28)
                pdf.cell(190, 5, txt="OBSERVACIONES DE CONCILIACION (SOBRANTES / FUERA DE OC / DIFERENCIAS):", ln=True)
                pdf.set_font("Helvetica", "", 8)
                for linea_inc in incidencias_acta[:8]:
                    pdf.cell(190, 4.5, txt=_txt_latin(linea_inc), ln=True)
                pdf.set_text_color(0, 0, 0)

            # --- FIRMAS DE CONFORMIDAD ---
            pdf.ln(12)
            y_f = pdf.get_y()
            if y_f > 250:
                pdf.add_page()
                y_f = 40
            pdf.set_draw_color(0, 0, 0)
            pdf.line(20, y_f + 14, 85, y_f + 14)
            pdf.line(125, y_f + 14, 190, y_f + 14)
            pdf.set_xy(20, y_f + 16)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(65, 5, "RECEPCION BODEGA", align="C")
            pdf.set_xy(125, y_f + 16)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(65, 5, "CONTROL DE CALIDAD / SUPERVISION", align="C")

            oc_limpio = _nombre_archivo_seguro_local(oc_num)
            ruta_out = os.path.join("reportes_recepcion", f"Acta_OC_{oc_limpio}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            pdf.output(ruta_out)
            return ruta_out

        def reimprimir_desde_fila(lpn_cod: str):
            """Genera y descarga en el navegador la etiqueta 15x10 cm de un LPN específico."""
            try:
                res = supabase.table("registro_recepcion").select("*").eq("lpn", lpn_cod).execute()
                filas_lpn = res.data or []
                if not filas_lpn:
                    notificar(f"No se encontraron datos para el LPN {lpn_cod}.", "#D97706")
                    return
                ruta = generar_pdf_recepcion_15x10(lpn_cod, filas_lpn)
                descargar_archivo_web(ruta, f"Etiqueta 15x10 - {lpn_cod}")
            except Exception as ex:
                notificar(f"Error generando etiqueta de {lpn_cod}: {ex}", "#B91C1C")

        def tarjeta_dark(contenido, padding=14, expand_val=None, height_val=None, width_val=None):
            return ft.Container(
                content=contenido,
                padding=padding,
                height=height_val,
                width=width_val,
                expand=expand_val,
                bgcolor=BG_CARD,
                border_radius=8,
                border=ft.Border.all(1, BORDER_COLOR),
                shadow=ft.BoxShadow(blur_radius=10, color="#40000000", offset=ft.Offset(0, 3)),
            )

        def texto_dark(label: str, width: int = None, expand=None, value: str = "", keyboard_type=None, on_change=None):
            return ft.TextField(
                label=label,
                width=width,
                expand=expand,
                value=value,
                dense=True,
                text_size=12,
                color=TEXT_WHITE,
                bgcolor=BG_INPUT,
                border_color=BORDER_COLOR,
                focused_border_color=ACCENT_CYAN,
                label_style=ft.TextStyle(size=11, color=TEXT_MUTED),
                content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                keyboard_type=keyboard_type,
                on_change=on_change,
                border_radius=6,
            )

        def opt_w(key, text):
            return ft.DropdownOption(
                key=key,
                text=text,
                content=ft.Container(
                    content=ft.Text(text, color=TEXT_WHITE, size=12),
                    alignment=ft.Alignment.CENTER_LEFT,
                ),
            )

        def dropdown_dark(label: str, width: int = None, expand=None, value: str = None, options: list = None):
            opts = []
            for o in (options or []):
                if isinstance(o, ft.DropdownOption) and not o.content:
                    opts.append(opt_w(o.key, o.text))
                else:
                    opts.append(o)
            return ft.Dropdown(
                label=label,
                width=width,
                expand=expand,
                value=value,
                options=opts,
                dense=True,
                color=TEXT_WHITE,
                bgcolor=BG_INPUT,
                border_color=BORDER_COLOR,
                focused_border_color=ACCENT_CYAN,
                text_style=ft.TextStyle(size=12, color=TEXT_WHITE),
                label_style=ft.TextStyle(size=11, color=TEXT_MUTED),
                content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                border_radius=6,
            )

        def crear_caja_digital(txt_control: ft.Text, etiqueta_inf: str, color_borde: str = "#6366F1", ancho: int = 88):
            return ft.Column(
                [
                    ft.Container(
                        width=ancho,
                        height=62,
                        bgcolor=BG_DIGITAL,
                        border_radius=6,
                        border=ft.Border.all(1.5, color_borde),
                        alignment=ft.Alignment.CENTER,
                        shadow=ft.BoxShadow(blur_radius=6, color="#33000000"),
                        content=txt_control,
                    ),
                    ft.Text(etiqueta_inf, size=10, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            )

        # --- 2. VARIABLES DE ESTADO ---
        asn_actual_id = None
        cabecera_asn_actual = {}
        lineas_asn_actual = []
        recepciones_asn_actual = []
        filas_conciliacion_export = []
        auto_sync_inbound_activo = False
        historico_filtrado_actual = []
        checks_hist_seleccionados = {}
        ultimos_filtrados_hist = []

        # --- 3. DEFINICIÓN DE TODOS LOS CONTROLES VISUALES BASE ---
        dd_asn = dropdown_dark(label="Orden de Compra Activa (N° OC | Nota PO)", expand=True)
        txt_po_netsuite = texto_dark(label="N° OC (Ej: 2043)", width=135)
        txt_contenedor = texto_dark(label="Contenedor / Guía", width=150)
        txt_ns_location_id = texto_dark(label="Location ID NS", value="1", width=105, keyboard_type=ft.KeyboardType.NUMBER)
        btn_guardar_contenedor = ft.IconButton(
            icon=ft.Icons.SAVE_OUTLINED,
            icon_color=ACCENT_CYAN,
            tooltip="Guardar N° Contenedor",
        )

        dd_accion_po = dropdown_dark(
            label="Operaciones de Recepción (OC/PO) - Clic para ejecutar",
            width=310,
            value=None,
            options=[
                opt_w("SINCRONIZAR", "1. Sincronizar Recepción de Andén (RF)"),
                opt_w("DESCARGAR_PO", "2. Descargar OC desde NetSuite (ERP)"),
                opt_w("PACKING", "3. Cargar Packing List / CAN CODE PDF (IA)"),
                opt_w("COA", "4. Anexar Certificado CoA PDF (IA)"),
                opt_w("IMPRIMIR_TODOS_LPN", "5. Imprimir TODOS los LPNs de la OC (15x10)"),
                opt_w("ACTA_PDF", "6. Exportar Acta Oficial de OC (PDF)"),
                opt_w("EXCEL", "7. Exportar Conciliación a Excel (.XLSX)"),
                opt_w("CSV_NETSUITE", "8. Generar CSV Item Receipt (NetSuite)"),
                opt_w("CERRAR_PO", "9. Cerrar OC + Emitir CSV NetSuite"),
            ],
        )

        txt_estado_ia = ft.Text(
            "Monitor en línea. Seleccione una OC o ejecute una acción.",
            size=11,
            color=ACCENT_CYAN,
        )
        txt_buscar_hist_rec = texto_dark(
            label="Buscar por N° OC/PO, Proveedor, LPN, SKU o Lote...",
            width=270,
        )
        dd_fecha_hist_rec = dropdown_dark(
            label="📅 Día de Recepción",
            width=245,
            value="TODAS",
            options=[opt_w("TODAS", "TODAS LAS FECHAS (POR DÍA)")],
        )
        txt_fecha_hist_rec = texto_dark(
            label="Día exacto (DD-MM-YYYY)",
            width=160,
        )
        fila_resumen_dias_hist = ft.Row(spacing=8, wrap=True)
        dd_mod_po_base = dropdown_dark(label="Orden de Compra (OC) Activa a Modificar", width=360)

        lbl_dig_dias = ft.Text("00", size=26, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_dig_horas = ft.Text("00", size=26, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_dig_min = ft.Text("00", size=26, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_inb_cajas = ft.Text("0/0", size=13, weight=ft.FontWeight.W_900, color="#34D399", font_family="Consolas")
        lbl_inb_unidades = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color=TEXT_WHITE, font_family="Consolas")
        lbl_inb_pallets = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color="#FBBF24", font_family="Consolas")
        lbl_inb_avance = ft.Text("0%", size=18, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")

        fila_barras_po = ft.Row(
            spacing=18,
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.END,
            scroll=ft.ScrollMode.AUTO,
        )

        dd_qa_po_base = dropdown_dark(label="1. Orden de Compra (OC) Base para QA", width=330)
        dd_qa_lpn = dropdown_dark(label="2. LPN a Bloquear / Desbloquear", width=210)
        dd_qa_estado = dropdown_dark(
            label="3. Dictamen de Calidad (QA)",
            width=220,
            value="APROBADO",
            options=[
                opt_w("APROBADO", "APROBADO (LIBRE USO)"),
                opt_w("CUARENTENA", "CUARENTENA (BLOQUEADO)"),
                opt_w("RECHAZADO", "RECHAZADO (MERMA / BLOQUEO)"),
            ],
        )

        # --- Controles 4.1 (Modificación Documental de Líneas de la OC) ---
        dd_edit_sku_asn = dropdown_dark(label="Seleccionar SKU de la OC", width=220)
        txt_nuevo_sku_po = texto_dark(label="O escribir SKU (Nuevo/Editar)", width=155)
        txt_edit_desc_po = texto_dark(label="Descripción Producto", width=220)
        txt_edit_cajas_esp = texto_dark(label="Cajas OC", width=90, keyboard_type=ft.KeyboardType.NUMBER)
        txt_edit_mult_esp = texto_dark(label="Múltiplo", width=85, keyboard_type=ft.KeyboardType.NUMBER)
        txt_edit_unid_esp = texto_dark(label="Unidades OC", width=105, keyboard_type=ft.KeyboardType.NUMBER)
        txt_edit_lote_sug = texto_dark(label="Lote / Can Code", width=130)
        txt_edit_venc_sug = texto_dark(label="Vencimiento (DD-MM-YYYY)", width=155)

        # --- Controles 4.2 (Filtro por SKU/LPN + Editor Unitario + Tabla de LPNs) ---
        dd_filtro_sku_mod_lpn = dropdown_dark(
            label="1. Elegir SKU (Filtra Tabla y LPNs)",
            width=265,
            value="TODOS",
            options=[opt_w("TODOS", "TODOS LOS SKUs")],
        )
        dd_edit_lpn_id = dropdown_dark(
            label="2. Elegir LPN Unitario a Modificar",
            width=340,
        )
        txt_buscar_lpn_mod = texto_dark(
            label="3. Buscar LPN, SKU o Lote...",
            width=200,
        )

        lbl_lpn_unitario_activo = ft.Text(
            "LPN Unitario Seleccionado: Ninguno",
            size=12,
            weight=ft.FontWeight.W_900,
            color=ACCENT_CYAN,
        )
        txt_mod_lpn_cod = texto_dark(label="Código LPN", width=150)
        txt_mod_lpn_sku = texto_dark(label="SKU", width=120)
        txt_mod_lpn_cajas = texto_dark(label="Cajas", width=85, keyboard_type=ft.KeyboardType.NUMBER)
        txt_mod_lpn_mult = texto_dark(label="Múltiplo", width=85, keyboard_type=ft.KeyboardType.NUMBER)
        txt_mod_lpn_sueltas = texto_dark(label="Sueltas", width=85, keyboard_type=ft.KeyboardType.NUMBER)
        txt_mod_lpn_totales = texto_dark(label="Unid. Totales", width=105, keyboard_type=ft.KeyboardType.NUMBER)
        txt_mod_lpn_lote = texto_dark(label="Lote Físico", width=130)
        txt_mod_lpn_venc = texto_dark(label="Vencimiento (DD-MM-YYYY)", width=150)
        dd_mod_lpn_qa = dropdown_dark(
            label="Estado QA",
            width=155,
            value="APROBADO",
            options=[
                opt_w("APROBADO", "APROBADO"),
                opt_w("CUARENTENA", "CUARENTENA"),
                opt_w("RECHAZADO", "RECHAZADO"),
            ],
        )

        lbl_resumen_lista_lpns = ft.Text(
            "Seleccione un SKU o un LPN arriba para ver todos sus pallets en la tabla y modificar cualquier LPN unitario.",
            size=11,
            weight=ft.FontWeight.BOLD,
            color="#34D399",
        )

        tabla_mod_lpns = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=32,
            data_row_max_height=38,
            column_spacing=14,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("ID", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("LPN PALLET", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("SKU", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("CAJAS", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                ft.DataColumn(ft.Text("MÚLTIPLO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("SUELTAS", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("UNID. TOTALES", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("LOTE FÍSICO", weight=ft.FontWeight.BOLD, size=11, color="#FBBF24")),
                ft.DataColumn(ft.Text("VENCIMIENTO", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("CALIDAD (QA)", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIÓN UNITARIA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )
        cont_tabla_mod_lpns = envolver_tabla_scroll(tabla_mod_lpns, 275)

        sw_auto_sync_rf = ft.Switch(
            label="Auto-Sync RF",
            value=False,
            active_color="#10B981",
        )

        # TABLAS PRINCIPALES
        tabla_cruce_inbound = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=30,
            data_row_max_height=36,
            column_spacing=16,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("PARTIDA / SKU", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("DESCRIPCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("EMPAQUE OC", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("UNID. OC", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("LOTE / VENC. (IA)", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("CAJAS REC.", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("UNID. REC. (RF)", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("LOTE / VENC. FÍSICO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("DIFERENCIA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ESTATUS", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        tabla_lpns_del_asn = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=30,
            data_row_max_height=36,
            column_spacing=16,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("LPN PALLET", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("SKU", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("CAJAS", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("MÚLTIPLO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("SUELTAS", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("UNID. TOTALES", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("LOTE", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("VENCIMIENTO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("CALIDAD (QA)", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ETIQUETA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        tabla_qa_lotes_po = ft.DataTable(
            heading_row_color="#1A2022",
            heading_row_height=34,
            data_row_min_height=32,
            data_row_max_height=38,
            column_spacing=14,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("LPN PALLET", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("SKU", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("CAJAS", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("UNIDADES", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("LOTE FISICO", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("VENCIMIENTO", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ESTADO QA", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCION RAPIDA", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        tabla_historico_recepciones = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=32,
            data_row_max_height=38,
            column_spacing=12,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("SEL.", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("FECHA RECEPCIÓN", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                ft.DataColumn(ft.Text("N° OC / PO", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("PROVEEDOR / REF.", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("LPN", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("SKU", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("CAJAS", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("MÚLT.", weight=ft.FontWeight.BOLD, size=11, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("UNID. TOTALES", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("LOTE", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("VENCIMIENTO", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("CALIDAD (QA)", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("REIMPRIMIR", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        cont_tabla_inb_cruce = envolver_tabla_scroll(tabla_cruce_inbound, 195)
        cont_tabla_inb_lpns = envolver_tabla_scroll(tabla_lpns_del_asn, 175)
        cont_tabla_qa_po = envolver_tabla_scroll(tabla_qa_lotes_po, 300)
        cont_tabla_hist_rec = envolver_tabla_scroll(tabla_historico_recepciones, 380)

        # --- 4. DEFINICIÓN DE TODAS LAS FUNCIONES DE LÓGICA ---
        def normalizar_fecha_sql(fecha_texto: str):
            texto = (fecha_texto or "").strip()
            if not texto or texto.upper() in ("S/F", "NONE", "NULL", "-"):
                return None
            for fmt in (
                "%d-%m-%Y",
                "%d/%m/%Y",
                "%Y-%m-%d",
                "%Y/%m/%d",
                "%d.%m.%Y",
                "%m.%d.%Y",
                "%m/%d/%Y",
                "%Y.%m.%d",
            ):
                try:
                    return datetime.strptime(texto, fmt).strftime("%d-%m-%Y")
                except ValueError:
                    continue
            return texto.replace("/", "-").replace(".", "-")

        def _extraer_sku_limpio_dropdown(val_raw: str) -> str:
            """Extrae siempre la clave limpia del SKU aunque el Dropdown entregue el texto descriptivo."""
            s = str(val_raw or "").strip().upper()
            if not s or s.startswith("TODOS"):
                return "TODOS"
            if " (" in s:
                s = s.split(" (", 1)[0].strip()
            if " - " in s:
                s = s.split(" - ", 1)[0].strip()
            return s

        def _extraer_id_lpn_limpio_dropdown(val_raw: str) -> str:
            """Extrae siempre el ID numérico del registro LPN aunque el Dropdown entregue el texto completo."""
            s = str(val_raw or "").strip()
            if not s:
                return ""
            if "|" in s:
                s = s.split("|", 1)[0].strip()
            return s.replace("#", "").strip()

        def recalcular_mod_lpn_totales(e=None):
            try:
                c = max(0, int((txt_mod_lpn_cajas.value or "0").strip()))
                m = max(1, int((txt_mod_lpn_mult.value or "1").strip()))
                s = max(0, int((txt_mod_lpn_sueltas.value or "0").strip()))
                txt_mod_lpn_totales.value = str((c * m) + s)
                page.update()
            except Exception:
                pass

        def recalcular_mod_po_unidades(e=None):
            try:
                c = max(1, int((txt_edit_cajas_esp.value or "1").strip()))
                m = max(1, int((txt_edit_mult_esp.value or "1").strip()))
                txt_edit_unid_esp.value = str(c * m)
                page.update()
            except Exception:
                pass

        # =====================================================================
        # LÓGICA SECCIÓN 4.2: FILTRO SKU/LPN + EDITOR UNITARIO + TABLA DE LPNs
        # =====================================================================
        def cargar_lpn_en_editor_unitario(id_registro_str: str, refrescar_tabla: bool = True):
            id_limpio = _extraer_id_lpn_limpio_dropdown(id_registro_str)
            if not id_limpio:
                lbl_lpn_unitario_activo.value = "LPN Unitario Seleccionado: Ninguno"
                txt_mod_lpn_cod.value = ""
                txt_mod_lpn_sku.value = ""
                txt_mod_lpn_cajas.value = "0"
                txt_mod_lpn_mult.value = "1"
                txt_mod_lpn_sueltas.value = "0"
                txt_mod_lpn_totales.value = "0"
                txt_mod_lpn_lote.value = ""
                txt_mod_lpn_venc.value = ""
                page.update()
                return

            reg = next((r for r in recepciones_asn_actual if str(r.get("id")) == id_limpio), None)
            if reg:
                dd_edit_lpn_id.value = id_limpio
                lote_limpio, qa_actual = extraer_estado_qa(reg.get("lote", "S/L"))
                lbl_lpn_unitario_activo.value = (
                    f"EDITANDO LPN UNITARIO: #{reg.get('id')}  •  {reg.get('lpn')}  •  SKU: {reg.get('sku')}"
                )
                txt_mod_lpn_cod.value = str(reg.get("lpn") or "")
                txt_mod_lpn_sku.value = str(reg.get("sku") or "")
                txt_mod_lpn_cajas.value = str(reg.get("cajas") or 0)
                txt_mod_lpn_mult.value = str(reg.get("multiplo_aplicado") or 1)
                txt_mod_lpn_sueltas.value = str(reg.get("unidades_sueltas") or 0)
                txt_mod_lpn_totales.value = str(reg.get("unidades_totales") or 0)
                txt_mod_lpn_lote.value = lote_limpio
                txt_mod_lpn_venc.value = str(reg.get("fecha_vencimiento_cl") or "")
                dd_mod_lpn_qa.value = qa_actual if qa_actual in ("APROBADO", "CUARENTENA", "RECHAZADO") else "APROBADO"
                if refrescar_tabla:
                    actualizar_tabla_y_selector_lpns(mantener_lpn_actual=True)
                else:
                    page.update()

        def evento_seleccionar_lpn_dropdown(e=None):
            val_raw = ""
            if e is not None:
                ctrl_ev = getattr(e, "control", None)
                val_raw = getattr(e, "data", None) or getattr(ctrl_ev, "value", None) or dd_edit_lpn_id.value
            else:
                val_raw = dd_edit_lpn_id.value
            cargar_lpn_en_editor_unitario(str(val_raw or ""), refrescar_tabla=True)

        def actualizar_tabla_y_selector_lpns(e=None, mantener_lpn_actual: bool = False):
            if e is not None:
                ctrl_ev = getattr(e, "control", None)
                if ctrl_ev == dd_filtro_sku_mod_lpn:
                    val_ev = getattr(e, "data", None) or getattr(ctrl_ev, "value", None)
                    if val_ev:
                        dd_filtro_sku_mod_lpn.value = _extraer_sku_limpio_dropdown(val_ev)

            sku_sel = _extraer_sku_limpio_dropdown(dd_filtro_sku_mod_lpn.value)
            dd_filtro_sku_mod_lpn.value = sku_sel
            busqueda_txt = (txt_buscar_lpn_mod.value or "").strip().upper()

            lista_filtrada = []
            for r in recepciones_asn_actual:
                s_r = str(r.get("sku") or "").strip().upper()
                lpn_r = str(r.get("lpn") or "").strip().upper()
                lote_r, _ = extraer_estado_qa(r.get("lote", "S/L"))
                id_r = str(r.get("id") or "")

                if sku_sel != "TODOS" and s_r != sku_sel:
                    continue
                if busqueda_txt and not any(busqueda_txt in c for c in (s_r, lpn_r, lote_r.upper(), id_r)):
                    continue
                lista_filtrada.append(r)

            # 1. Actualizar opciones del Dropdown de LPN Unitario (2. Elegir LPN Unitario)
            dd_edit_lpn_id.options = [
                opt_w(
                    str(r["id"]),
                    f"#{r['id']} | {r.get('lpn')} | SKU: {r.get('sku')} | {r.get('cajas', 0)} Cj ({r.get('unidades_totales', 0)} UN) | Lote: {extraer_estado_qa(r.get('lote', 'S/L'))[0]}",
                )
                for r in lista_filtrada
            ]

            id_activo = _extraer_id_lpn_limpio_dropdown(dd_edit_lpn_id.value)
            ids_disp = [str(r["id"]) for r in lista_filtrada]

            if lista_filtrada:
                if not mantener_lpn_actual or id_activo not in ids_disp:
                    id_activo = ids_disp[0]
                    cargar_lpn_en_editor_unitario(id_activo, refrescar_tabla=False)
            else:
                id_activo = ""
                cargar_lpn_en_editor_unitario("", refrescar_tabla=False)

            # 2. Poblar la Tabla Interactiva de LPNs (tabla_mod_lpns)
            tabla_mod_lpns.rows.clear()
            tot_cajas_f = sum(int(x.get("cajas") or 0) for x in lista_filtrada)
            tot_unid_f = sum(int(x.get("unidades_totales") or 0) for x in lista_filtrada)
            etiqueta_sku = f"SKU {sku_sel}" if sku_sel != "TODOS" else "TODOS LOS SKUs"
            lbl_resumen_lista_lpns.value = (
                f"Tabla de Pallets ({etiqueta_sku}): {len(lista_filtrada)} LPN(s) encontrados   |   Total: {tot_cajas_f} Cajas ({tot_unid_f} Unidades)"
            )

            for r in lista_filtrada:
                id_str = str(r.get("id"))
                lpn_cod = str(r.get("lpn") or "-")
                sku_r = str(r.get("sku") or "-")
                lote_c, qa_c = extraer_estado_qa(r.get("lote", "S/L"))
                es_fila_activa = (id_str == id_activo)

                badge_qa = (
                    crear_badge_estado("APROBADO", "#065F46", "#D1FAE5")
                    if qa_c == "APROBADO"
                    else (
                        crear_badge_estado("CUARENTENA", "#92400E", "#FEF3C7")
                        if qa_c == "CUARENTENA"
                        else crear_badge_estado("RECHAZADO", "#991B1B", "#FEE2E2")
                    )
                )

                tabla_mod_lpns.rows.append(
                    ft.DataRow(
                        color="#1E3A5F" if es_fila_activa else None,
                        cells=[
                            ft.DataCell(
                                ft.Text(
                                    f"#{id_str}",
                                    weight=ft.FontWeight.BOLD,
                                    size=11,
                                    color=ACCENT_CYAN if es_fila_activa else TEXT_MUTED,
                                )
                            ),
                            ft.DataCell(ft.Text(lpn_cod, weight=ft.FontWeight.W_900, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(sku_r, weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(f"{r.get('cajas', 0)} Cj", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                            ft.DataCell(ft.Text(f"x{r.get('multiplo_aplicado', 1)}", size=11, color=TEXT_MUTED)),
                            ft.DataCell(ft.Text(str(r.get("unidades_sueltas", 0)), size=11, color=TEXT_MUTED)),
                            ft.DataCell(ft.Text(f"{r.get('unidades_totales', 0)} UN", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(lote_c, weight=ft.FontWeight.BOLD, size=11, color="#FBBF24")),
                            ft.DataCell(ft.Text(str(r.get("fecha_vencimiento_cl") or "S/F"), size=11, color=TEXT_WHITE)),
                            ft.DataCell(badge_qa),
                            ft.DataCell(
                                ft.Row(
                                    [
                                        boton_primario(
                                            "EDITANDO" if es_fila_activa else "EDITAR",
                                            ft.Icons.EDIT_NOTE_ROUNDED,
                                            lambda ev, id_sel=id_str: cargar_lpn_en_editor_unitario(id_sel, refrescar_tabla=True),
                                            "#0284C7" if not es_fila_activa else "#047857",
                                            height_val=26,
                                        ),
                                        boton_primario(
                                            "15x10",
                                            ft.Icons.PRINT_OUTLINED,
                                            lambda ev, cod=lpn_cod: reimprimir_desde_fila(cod),
                                            ACCENT_TEAL,
                                            height_val=26,
                                        ),
                                        boton_primario(
                                            "BORRAR",
                                            ft.Icons.DELETE_OUTLINE,
                                            lambda ev, id_del=id_str, cod_del=lpn_cod: eliminar_lpn_por_id(id_del, cod_del),
                                            "#B91C1C",
                                            height_val=26,
                                        ),
                                    ],
                                    spacing=4,
                                )
                            ),
                        ],
                    )
                )
            page.update()

        def guardar_modificacion_lpn_fisico(e=None):
            id_sel = _extraer_id_lpn_limpio_dropdown(dd_edit_lpn_id.value)
            if not id_sel:
                notificar("Seleccione primero un LPN en el selector o en la tabla inferior.", "#D97706")
                return
            try:
                cajas_n = max(0, int((txt_mod_lpn_cajas.value or "0").strip()))
                mult_n = max(1, int((txt_mod_lpn_mult.value or "1").strip()))
                sueltas_n = max(0, int((txt_mod_lpn_sueltas.value or "0").strip()))
                unid_calc = (cajas_n * mult_n) + sueltas_n
                unid_n = max(1, int((txt_mod_lpn_totales.value or str(unid_calc)).strip()))

                lpn_n = (txt_mod_lpn_cod.value or "").strip().upper()
                sku_n = (txt_mod_lpn_sku.value or "").strip().upper()
                lote_n = formatear_lote_con_qa((txt_mod_lpn_lote.value or "S/L").strip().upper(), dd_mod_lpn_qa.value or "APROBADO")
                venc_n = normalizar_fecha_sql(txt_mod_lpn_venc.value)

                supabase.table("registro_recepcion").update(
                    {
                        "lpn": lpn_n,
                        "sku": sku_n,
                        "cajas": cajas_n,
                        "multiplo_aplicado": mult_n,
                        "unidades_sueltas": sueltas_n,
                        "unidades_totales": unid_n,
                        "lote": lote_n,
                        "fecha_vencimiento_cl": venc_n,
                    }
                ).eq("id", int(id_sel)).execute()

                notificar(f"LPN {lpn_n} (#{id_sel}) modificado exitosamente.", "#047857")
                auditar_asn_seleccionado()
            except Exception as ex:
                notificar(f"Error modificando LPN: {ex}", "#B91C1C")

        def eliminar_lpn_por_id(id_str: str, cod_lpn: str = ""):
            id_limpio = _extraer_id_lpn_limpio_dropdown(id_str)
            if not id_limpio:
                return
            try:
                supabase.table("registro_recepcion").delete().eq("id", int(id_limpio)).execute()
                notificar(f"Registro LPN {cod_lpn} (#{id_limpio}) eliminado.", "#047857")
                if _extraer_id_lpn_limpio_dropdown(dd_edit_lpn_id.value) == id_limpio:
                    dd_edit_lpn_id.value = None
                auditar_asn_seleccionado()
            except Exception as ex:
                notificar(f"Error eliminando LPN: {ex}", "#B91C1C")

        def eliminar_lpn_fisico(e=None):
            id_sel = _extraer_id_lpn_limpio_dropdown(dd_edit_lpn_id.value)
            if not id_sel:
                notificar("Seleccione un LPN para eliminar.", "#D97706")
                return
            eliminar_lpn_por_id(id_sel, txt_mod_lpn_cod.value or "")

        def prellenar_edicion_linea_asn(e=None):
            if e is not None:
                ctrl_ev = getattr(e, "control", None)
                if ctrl_ev == dd_edit_sku_asn:
                    val_ev = getattr(e, "data", None) or getattr(ctrl_ev, "value", None)
                    if val_ev:
                        dd_edit_sku_asn.value = _extraer_sku_limpio_dropdown(val_ev)

            sku_sel = _extraer_sku_limpio_dropdown(dd_edit_sku_asn.value)
            linea = next((l for l in lineas_asn_actual if str(l.get("sku") or "").strip().upper() == sku_sel), None)
            if linea:
                txt_nuevo_sku_po.value = str(linea.get("sku") or "")
                txt_edit_desc_po.value = str(linea.get("descripcion_proveedor") or "")
                txt_edit_cajas_esp.value = str(linea.get("cajas_esperadas") or 1)
                txt_edit_mult_esp.value = str(linea.get("multiplo_empaque") or 1)
                txt_edit_unid_esp.value = str(linea.get("unidades_esperadas") or 1)
                txt_edit_lote_sug.value = str(linea.get("lote_sugerido") or "S/L")
                txt_edit_venc_sug.value = str(linea.get("vencimiento_sugerido_cl") or "")
                page.update()

        def actualizar_reloj_descarga(recepciones: list):
            if not recepciones:
                lbl_dig_dias.value = "00"
                lbl_dig_horas.value = "00"
                lbl_dig_min.value = "00"
                return
            fechas_validas = []
            for r in recepciones:
                for col_t in ("created_at", "fecha_recepcion", "timestamp"):
                    v = r.get(col_t)
                    if v and str(v).strip() not in ("None", ""):
                        try:
                            fechas_validas.append(datetime.fromisoformat(str(v).replace("Z", "+00:00")))
                            break
                        except Exception:
                            pass
            if len(fechas_validas) >= 2:
                delta = max(fechas_validas) - min(fechas_validas)
                lbl_dig_dias.value = f"{delta.days:02d}"
                lbl_dig_horas.value = f"{delta.seconds // 3600:02d}"
                lbl_dig_min.value = f"{(delta.seconds % 3600) // 60:02d}"
            elif len(fechas_validas) == 1:
                lbl_dig_dias.value, lbl_dig_horas.value, lbl_dig_min.value = "00", "00", "15"
            else:
                lbl_dig_dias.value, lbl_dig_horas.value, lbl_dig_min.value = "00", "00", f"{min(59, len(recepciones) * 4):02d}"

        def construir_columna_grafico(sku_lbl: str, unid_rec: int, unid_esp: int, max_escala: int, es_alerta: bool = False):
            altura_max_px = 105
            ratio = min(1.0, unid_rec / max(1, max_escala))
            alto_barra = max(14, int(ratio * altura_max_px))
            pct_sku = int(round((unid_rec / max(1, unid_esp)) * 100)) if unid_esp > 0 else 100
            if es_alerta:
                color_b = "#EF4444"
            else:
                color_b = "#10B981" if pct_sku >= 100 else (ACCENT_BLUE if pct_sku > 0 else "#475569")

            return ft.Column(
                [
                    ft.Text(f"{unid_rec}", size=10, color="#F87171" if es_alerta else TEXT_WHITE, weight=ft.FontWeight.BOLD),
                    ft.Container(
                        width=34,
                        height=altura_max_px,
                        bgcolor="#141A1C",
                        border_radius=4,
                        alignment=ft.Alignment.BOTTOM_CENTER,
                        content=ft.Container(
                            width=34,
                            height=alto_barra,
                            bgcolor=color_b,
                            border_radius=4,
                            alignment=ft.Alignment.CENTER,
                            tooltip=f"{sku_lbl}: {unid_rec} / {unid_esp} UN ({pct_sku}%)",
                        ),
                    ),
                    ft.Text(sku_lbl[:10], size=9, color="#F87171" if es_alerta else TEXT_MUTED, weight=ft.FontWeight.W_600),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=3,
            )

        def cambiar_qa_rapido_lpn(lpn_objetivo: str, nuevo_estado: str):
            try:
                res = supabase.table("registro_recepcion").select("*").eq("lpn", lpn_objetivo).execute()
                for fila in res.data:
                    lote_base, _ = extraer_estado_qa(fila.get("lote", "S/L"))
                    supabase.table("registro_recepcion").update({"lote": formatear_lote_con_qa(lote_base, nuevo_estado)}).eq("id", fila["id"]).execute()
                notificar(f"LPN {lpn_objetivo} -> Estado QA actualizado a [{nuevo_estado}].", "#047857")
                auditar_asn_seleccionado()
            except Exception as ex:
                notificar(f"Error cambiando QA: {ex}", "#B91C1C")

        def actualizar_dictamen_qa_lpn(e=None):
            lpn_sel = dd_qa_lpn.value
            nuevo_qa = dd_qa_estado.value or "APROBADO"
            if not lpn_sel:
                notificar("Seleccione un LPN de la OC para aplicar el dictamen de Calidad.", "#D97706")
                return
            cambiar_qa_rapido_lpn(lpn_sel, nuevo_qa)

        def aplicar_qa_masivo_toda_la_po(e=None):
            nuevo_qa = dd_qa_estado.value or "APROBADO"
            if not recepciones_asn_actual:
                notificar("No hay pallets registrados en esta OC.", "#D97706")
                return
            try:
                for fila in recepciones_asn_actual:
                    lote_base, _ = extraer_estado_qa(fila.get("lote", "S/L"))
                    supabase.table("registro_recepcion").update({"lote": formatear_lote_con_qa(lote_base, nuevo_qa)}).eq("id", fila["id"]).execute()
                notificar(f"Dictamen QA masivo [{nuevo_qa}] aplicado a los {len(recepciones_asn_actual)} registros de la OC.", "#047857")
                auditar_asn_seleccionado()
            except Exception as ex:
                notificar(f"Error en liberación masiva QA: {ex}", "#B91C1C")

        def auditar_asn_seleccionado(e=None):
            nonlocal asn_actual_id, cabecera_asn_actual, lineas_asn_actual, recepciones_asn_actual, filas_conciliacion_export
            if e is not None:
                ctrl_ev = getattr(e, "control", None)
                if ctrl_ev == dd_asn:
                    val_ev = getattr(e, "data", None) or getattr(ctrl_ev, "value", None)
                    if val_ev:
                        dd_asn.value = str(val_ev)

            if not dd_asn.value:
                return
            dd_qa_po_base.value = dd_asn.value
            dd_mod_po_base.value = dd_asn.value

            try:
                bodega_act = obtener_bodega_actual()
                if dd_asn.value == "LIBRES":
                    asn_actual_id = None
                    cabecera_asn_actual = {
                        "codigo_asn": "OC-LIBRE",
                        "proveedor": f"RECEPCION DIRECTA SIN OC ({bodega_act})",
                        "numero_oc": "S/OC",
                        "estado": "ACTIVO",
                        "contenedor_referencia": "",
                        "bodega": bodega_act,
                    }
                    lineas_asn_actual = []
                    res_lib = (
                        supabase.table("registro_recepcion")
                        .select("*")
                        .is_("asn_id", "null")
                        .order("id", desc=True)
                        .limit(150)
                        .execute()
                    )
                    recepciones_asn_actual = [r for r in (res_lib.data or []) if coincide_bodega_fila(r, bodega_act)][:100]
                else:
                    asn_actual_id = int(dd_asn.value)
                    res_cab = supabase.table("asn_cabecera").select("*").eq("id", asn_actual_id).execute()
                    cabecera_asn_actual = res_cab.data[0] if res_cab.data else {}
                    lineas_asn_actual = supabase.table("asn_detalle").select("*").eq("asn_id", asn_actual_id).order("sku").execute().data
                    recepciones_asn_actual = supabase.table("registro_recepcion").select("*").eq("asn_id", asn_actual_id).order("id", desc=True).execute().data

                skus_po_set = {str(l.get("sku") or "").strip().upper() for l in lineas_asn_actual if l.get("sku")}
                skus_po_set.update({str(r.get("sku") or "").strip().upper() for r in recepciones_asn_actual if r.get("sku")})
                mapa_nombres_maestra, _ = consultar_maestra_por_skus(skus_po_set)

                # Limpieza automática de fechas antiguas en lote_sugerido
                reg_fecha_antigua = re.compile(r"^\d{1,4}[\-\/\.]\d{1,2}[\-\/\.]\d{1,4}$")
                for lin_oc in lineas_asn_actual:
                    l_sug_raw = str(lin_oc.get("lote_sugerido") or "").strip()
                    if l_sug_raw and l_sug_raw != "S/L":
                        partes_l = [p.strip() for p in l_sug_raw.split(",") if p.strip()]
                        lotes_reales_ia = [p for p in partes_l if not reg_fecha_antigua.match(p)]
                        fechas_en_lote = [normalizar_fecha_sql(p) for p in partes_l if reg_fecha_antigua.match(p)]
                        if len(lotes_reales_ia) != len(partes_l):
                            nuevo_lote_s = ", ".join(lotes_reales_ia) if lotes_reales_ia else "S/L"
                            venc_actual = str(lin_oc.get("vencimiento_sugerido_cl") or "").strip()
                            if (not venc_actual or venc_actual == "S/F") and fechas_en_lote:
                                venc_actual = ", ".join([f for f in fechas_en_lote if f])
                            else:
                                venc_actual = normalizar_fecha_sql(venc_actual) or venc_actual
                            lin_oc["lote_sugerido"] = nuevo_lote_s
                            lin_oc["vencimiento_sugerido_cl"] = venc_actual
                            if lin_oc.get("id"):
                                try:
                                    supabase.table("asn_detalle").update({
                                        "lote_sugerido": nuevo_lote_s,
                                        "vencimiento_sugerido_cl": venc_actual,
                                    }).eq("id", lin_oc["id"]).execute()
                                except Exception:
                                    pass

                actualizar_reloj_descarga(recepciones_asn_actual)
                txt_contenedor.value = str(cabecera_asn_actual.get("contenedor_referencia") or "")

                dd_edit_sku_asn.options = [opt_w(l["sku"], f"{l['sku']} - {str(l.get('descripcion_proveedor',''))[:30]}") for l in lineas_asn_actual]
                if lineas_asn_actual and (not dd_edit_sku_asn.value or _extraer_sku_limpio_dropdown(dd_edit_sku_asn.value) not in [str(l["sku"]).upper() for l in lineas_asn_actual]):
                    dd_edit_sku_asn.value = lineas_asn_actual[0]["sku"]
                    prellenar_edicion_linea_asn()

                lpns_lista = sorted({str(r.get("lpn")) for r in recepciones_asn_actual if r.get("lpn")})
                dd_qa_lpn.options = [opt_w(c, c) for c in lpns_lista]
                if lpns_lista and (not dd_qa_lpn.value or dd_qa_lpn.value not in lpns_lista):
                    dd_qa_lpn.value = lpns_lista[0]

                # Poblar selector 1. Elegir SKU en sección 4.2
                resumen_sku_lpns = {}
                for r in recepciones_asn_actual:
                    s_r = str(r.get("sku") or "").strip().upper()
                    if not s_r:
                        continue
                    if s_r not in resumen_sku_lpns:
                        resumen_sku_lpns[s_r] = {"lpns": 0, "cajas": 0, "unid": 0}
                    resumen_sku_lpns[s_r]["lpns"] += 1
                    resumen_sku_lpns[s_r]["cajas"] += int(r.get("cajas") or 0)
                    resumen_sku_lpns[s_r]["unid"] += int(r.get("unidades_totales") or 0)

                opts_sku_mod = [opt_w("TODOS", f"TODOS LOS SKUs ({len(recepciones_asn_actual)} LPNs)")]
                for s_k, inf_s in sorted(resumen_sku_lpns.items()):
                    opts_sku_mod.append(
                        opt_w(s_k, f"{s_k} ({inf_s['lpns']} LPNs | {inf_s['cajas']} Cj | {inf_s['unid']} UN)")
                    )
                dd_filtro_sku_mod_lpn.options = opts_sku_mod
                sku_f_actual = _extraer_sku_limpio_dropdown(dd_filtro_sku_mod_lpn.value)
                claves_validas_sku = ["TODOS"] + list(resumen_sku_lpns.keys())
                if sku_f_actual not in claves_validas_sku:
                    dd_filtro_sku_mod_lpn.value = "TODOS"
                else:
                    dd_filtro_sku_mod_lpn.value = sku_f_actual

                actualizar_tabla_y_selector_lpns(mantener_lpn_actual=True)

                mapa_rec_sku = {}
                for r in recepciones_asn_actual:
                    s = str(r.get("sku") or "").strip().upper()
                    if not s:
                        continue
                    lote_c, _ = extraer_estado_qa(r.get("lote", "S/L"))
                    if s not in mapa_rec_sku:
                        mapa_rec_sku[s] = {
                            "cajas": 0,
                            "unidades": 0,
                            "multiplo": int(r.get("multiplo_aplicado") or 1),
                            "lotes": set(),
                            "vencimientos": set(),
                        }
                    mapa_rec_sku[s]["cajas"] += int(r.get("cajas") or 0)
                    mapa_rec_sku[s]["unidades"] += int(r.get("unidades_totales") or 0)
                    if lote_c:
                        mapa_rec_sku[s]["lotes"].add(lote_c)
                    if r.get("fecha_vencimiento_cl"):
                        mapa_rec_sku[s]["vencimientos"].add(str(r.get("fecha_vencimiento_cl")))

                tabla_cruce_inbound.rows.clear()
                filas_conciliacion_export.clear()
                fila_barras_po.controls.clear()

                total_cajas_esp, total_cajas_rec, total_unid_esp, total_unid_rec = 0, 0, 0, 0
                es_recepcion_libre = (dd_asn.value == "LIBRES" or not lineas_asn_actual)

                fuente_lineas = [dict(x, fuera_de_oc=False) for x in lineas_asn_actual]
                skus_en_fuente = {str(x.get("sku") or "").strip().upper() for x in fuente_lineas}

                for k_rec, v_rec in sorted(mapa_rec_sku.items()):
                    if k_rec not in skus_en_fuente:
                        fuente_lineas.append(
                            {
                                "id": None,
                                "sku": k_rec,
                                "descripcion_proveedor": mapa_nombres_maestra.get(k_rec, "ARTÍCULO NO INCLUIDO EN OC"),
                                "cajas_esperadas": v_rec["cajas"] if es_recepcion_libre else 0,
                                "multiplo_empaque": v_rec["multiplo"],
                                "unidades_esperadas": v_rec["unidades"] if es_recepcion_libre else 0,
                                "lote_sugerido": "NO EN OC" if not es_recepcion_libre else "S/L",
                                "vencimiento_sugerido_cl": "-",
                                "fuera_de_oc": not es_recepcion_libre,
                            }
                        )

                max_unid_grafico = max(
                    [int(l.get("unidades_esperadas") or 1) for l in fuente_lineas]
                    + [v["unidades"] for v in mapa_rec_sku.values()]
                    + [1]
                )

                alertas_sobrantes = []

                for l in fuente_lineas:
                    sku_code = str(l["sku"]).strip().upper()
                    es_fuera_oc = bool(l.get("fuera_de_oc"))
                    desc_completa = mapa_nombres_maestra.get(sku_code) or str(l.get("descripcion_proveedor") or "-")
                    cajas_esp = int(l.get("cajas_esperadas") or 0)
                    mult_emp = int(l.get("multiplo_empaque") or 1)
                    unid_esp = 0 if es_fuera_oc else int(l.get("unidades_esperadas") or (cajas_esp * mult_emp))

                    info_fisica = mapa_rec_sku.get(sku_code, None)
                    if info_fisica:
                        cajas_rec = info_fisica["cajas"]
                        unid_rec = info_fisica["unidades"]
                        lotes_reales = ", ".join(sorted(info_fisica["lotes"])) or "S/L"
                        venc_reales = ", ".join(sorted(info_fisica["vencimientos"])) or "S/F"
                    else:
                        cajas_rec, unid_rec, lotes_reales, venc_reales = 0, int(l.get("unidades_recibidas") or 0), "SIN INGRESO", "-"

                    if info_fisica and l.get("id") and unid_rec != int(l.get("unidades_recibidas") or 0):
                        try:
                            supabase.table("asn_detalle").update({"unidades_recibidas": unid_rec}).eq("id", l["id"]).execute()
                        except Exception:
                            pass

                    total_cajas_esp += cajas_esp
                    total_cajas_rec += cajas_rec
                    total_unid_esp += unid_esp
                    total_unid_rec += unid_rec

                    dif_unid = unid_rec - unid_esp
                    dif_cajas = cajas_rec - cajas_esp
                    es_alerta_fila = False

                    if es_fuera_oc:
                        txt_dif = f"+{unid_rec} UN (+{cajas_rec} Cj)"
                        color_dif = "#F87171"
                        estado_txt = "SKU FUERA DE OC"
                        badge_linea = crear_badge_estado("SKU FUERA DE OC", "#991B1B", "#FEE2E2")
                        es_alerta_fila = True
                        alertas_sobrantes.append(f"{sku_code} (Fuera de OC: +{cajas_rec} Cj)")
                    elif unid_rec > unid_esp or (cajas_esp > 0 and cajas_rec > cajas_esp):
                        txt_dif = f"{dif_unid:+d} UN ({dif_cajas:+d} Cj)"
                        color_dif = "#F87171"
                        estado_txt = "SOBRANTE"
                        badge_linea = crear_badge_estado(f"SOBRANTE ({dif_cajas:+d} CJ)", "#991B1B", "#FEE2E2")
                        es_alerta_fila = True
                        alertas_sobrantes.append(f"{sku_code} (Sobrante: {dif_cajas:+d} Cj / {dif_unid:+d} UN)")
                    elif dif_unid == 0 and unid_esp > 0 and (cajas_esp == 0 or cajas_rec == cajas_esp):
                        txt_dif = "0 (OK)"
                        color_dif = "#34D399"
                        estado_txt = "VALIDADA"
                        badge_linea = crear_badge_estado("VALIDADA", "#065F46", "#D1FAE5")
                    elif unid_rec == 0 and cajas_rec == 0:
                        txt_dif = f"-{unid_esp} UN (-{cajas_esp} Cj)"
                        color_dif = TEXT_MUTED
                        estado_txt = "PENDIENTE"
                        badge_linea = crear_badge_estado("PENDIENTE", "#CBD5E1", "#334155")
                    else:
                        txt_dif = f"{dif_unid:+d} UN ({dif_cajas:+d} Cj)"
                        color_dif = "#FBBF24"
                        estado_txt = "PARCIAL"
                        badge_linea = crear_badge_estado("PARCIAL", "#92400E", "#FEF3C7")

                    filas_conciliacion_export.append(
                        {
                            "sku": sku_code,
                            "descripcion": desc_completa,
                            "cajas_esperadas": cajas_esp,
                            "multiplo": mult_emp,
                            "unidades_esperadas": unid_esp,
                            "cajas_recibidas": cajas_rec,
                            "unidades_recibidas": unid_rec,
                            "diferencia": dif_unid,
                            "dif_cajas": dif_cajas,
                            "lotes_reales": f"{lotes_reales} ({venc_reales})",
                            "estado": estado_txt,
                        }
                    )
                    fila_barras_po.controls.append(
                        construir_columna_grafico(sku_code, unid_rec, unid_esp, max_unid_grafico, es_alerta=es_alerta_fila)
                    )

                    tabla_cruce_inbound.rows.append(
                        ft.DataRow(
                            color="#3B1818" if es_alerta_fila else None,
                            cells=[
                                ft.DataCell(ft.Text(sku_code, weight=ft.FontWeight.BOLD, size=11, color="#F87171" if es_alerta_fila else ACCENT_CYAN)),
                                ft.DataCell(ft.Text(desc_completa[:28], size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text("NO EN OC (0 Cj)" if es_fuera_oc else f"{cajas_esp} Cj x {mult_emp}", size=11, color="#F87171" if es_fuera_oc else TEXT_MUTED)),
                                ft.DataCell(ft.Text(f"{unid_esp} UN", size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"{str(l.get('lote_sugerido') or 'S/L')} | {str(l.get('vencimiento_sugerido_cl') or 'S/F')}", size=11, color="#FBBF24" if l.get("lote_sugerido") and l.get("lote_sugerido") not in ("S/L", "NO EN OC") else TEXT_MUTED)),
                                ft.DataCell(ft.Text(f"{cajas_rec} Cj", weight=ft.FontWeight.BOLD, size=11, color="#F87171" if es_alerta_fila else TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"{unid_rec} UN", weight=ft.FontWeight.BOLD, color="#F87171" if es_alerta_fila else ACCENT_CYAN, size=11)),
                                ft.DataCell(ft.Text(f"{lotes_reales} | {venc_reales}", size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(txt_dif, weight=ft.FontWeight.BOLD, color=color_dif, size=11)),
                                ft.DataCell(badge_linea),
                            ],
                        )
                    )

                if alertas_sobrantes:
                    txt_estado_ia.value = f"⚠ ALERTA DE DISCREPANCIA: {', '.join(alertas_sobrantes[:3])}"
                    txt_estado_ia.color = "#F87171"
                else:
                    txt_estado_ia.value = f"[{bodega_act}] Monitor en línea. Seleccione una OC o ejecute una acción."
                    txt_estado_ia.color = ACCENT_CYAN

                tabla_lpns_del_asn.rows.clear()
                tabla_qa_lotes_po.rows.clear()

                for r in recepciones_asn_actual:
                    lpn_cod = str(r.get("lpn", "-"))
                    lote_c, qa_c = extraer_estado_qa(r.get("lote", "S/L"))
                    badge_qa = (
                        crear_badge_estado("APROBADO", "#065F46", "#D1FAE5")
                        if qa_c == "APROBADO"
                        else (
                            crear_badge_estado("CUARENTENA", "#92400E", "#FEF3C7")
                            if qa_c == "CUARENTENA"
                            else crear_badge_estado("RECHAZADO", "#991B1B", "#FEE2E2")
                        )
                    )

                    tabla_lpns_del_asn.rows.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(lpn_cod, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN, size=11)),
                                ft.DataCell(ft.Text(str(r.get("sku", "-")), weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(str(r.get("cajas", 0)), size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"x{r.get('multiplo_aplicado', 1)}", size=11, color=TEXT_MUTED)),
                                ft.DataCell(ft.Text(str(r.get("unidades_sueltas", 0)), size=11, color=TEXT_MUTED)),
                                ft.DataCell(ft.Text(str(r.get("unidades_totales", 0)), weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(lote_c, size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(str(r.get("fecha_vencimiento_cl") or "S/F"), size=11, color=TEXT_WHITE)),
                                ft.DataCell(badge_qa),
                                ft.DataCell(boton_primario("LPN 15x10", ft.Icons.PRINT_OUTLINED, lambda e, cod=lpn_cod: reimprimir_desde_fila(cod), ACCENT_TEAL, height_val=26)),
                            ]
                        )
                    )
                    tabla_qa_lotes_po.rows.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(lpn_cod, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN, size=11)),
                                ft.DataCell(ft.Text(str(r.get("sku", "-")), weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(str(r.get("cajas", 0)), size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(str(r.get("unidades_totales", 0)), weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(lote_c, weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(str(r.get("fecha_vencimiento_cl") or "S/F"), size=11, color=TEXT_WHITE)),
                                ft.DataCell(badge_qa),
                                ft.DataCell(
                                    ft.Row(
                                        [
                                            boton_primario("LIBERAR", ft.Icons.CHECK_CIRCLE_OUTLINE, lambda ev, c=lpn_cod: cambiar_qa_rapido_lpn(c, "APROBADO"), "#047857", height_val=26),
                                            boton_primario("BLOQUEAR", ft.Icons.LOCK_OUTLINE, lambda ev, c=lpn_cod: cambiar_qa_rapido_lpn(c, "CUARENTENA"), "#D97706", height_val=26),
                                        ],
                                        spacing=4,
                                    )
                                ),
                            ]
                        )
                    )

                lbl_inb_cajas.value = f"{total_cajas_rec}/{total_cajas_esp}"
                lbl_inb_unidades.value = f"{total_unid_rec}"
                lbl_inb_pallets.value = f"{len(lpns_lista)}"
                pct_global = int(round((total_unid_rec / max(1, total_unid_esp)) * 100)) if total_unid_esp > 0 else 0
                lbl_inb_avance.value = f"{pct_global}%"
                page.update()
            except Exception as ex:
                notificar(f"Error auditando OC: {ex}", "#B91C1C")

        def guardar_contenedor_db(e=None):
            if asn_actual_id:
                val = (txt_contenedor.value or "").strip().upper()
                try:
                    supabase.table("asn_cabecera").update({"contenedor_referencia": val}).eq("id", asn_actual_id).execute()
                    cabecera_asn_actual["contenedor_referencia"] = val
                    notificar(f"Contenedor guardado: {val}", "#047857")
                except Exception as ex:
                    notificar(f"Error al guardar el contenedor: {ex}", "#B91C1C")
            else:
                notificar("Seleccione una OC activa primero.", "#D97706")

        def cargar_lista_asns(e=None):
            try:
                bodega_act = obtener_bodega_actual()
                res = supabase.table("asn_cabecera").select("*").neq("estado", "COMPLETADO").order("id", desc=True).execute()
                filas_bodega = [r for r in (res.data or []) if coincide_bodega_fila(r, bodega_act)]

                opciones = [opt_w("LIBRES", f"RECEPCIONES DIRECTAS SIN OC ({bodega_act.upper()})")]
                for r in filas_bodega:
                    oc_num = str(r.get("numero_oc") or "").strip()
                    cod_asn = str(r.get("codigo_asn") or "").strip()
                    nota_po = ""
                    if "|" in cod_asn:
                        nota_po = cod_asn.split("|", 1)[1].strip()
                    elif cod_asn and cod_asn != f"OC-{oc_num}" and cod_asn != f"PO-{oc_num}":
                        nota_po = cod_asn

                    id_principal = oc_num if oc_num and oc_num not in ("S/OC", "NONE") else formatear_nombre_po(cod_asn)
                    txt_nota = f" (Nota: {nota_po})" if nota_po else ""
                    opciones.append(
                        opt_w(
                            str(r["id"]),
                            f"OC {id_principal}{txt_nota} | {r.get('proveedor','')} | {r.get('estado','ACTIVO')}",
                        )
                    )
                dd_asn.options = opciones
                dd_qa_po_base.options = list(opciones)
                dd_mod_po_base.options = list(opciones)
                valores_validos = [o.key for o in opciones]
                if not dd_asn.value or dd_asn.value not in valores_validos:
                    dd_asn.value = str(filas_bodega[0]["id"]) if filas_bodega else "LIBRES"
                dd_qa_po_base.value = dd_asn.value
                dd_mod_po_base.value = dd_asn.value
                auditar_asn_seleccionado()
                page.update()
            except Exception as ex:
                notificar(f"Error al cargar OCs: {ex}", "#B91C1C")

        def extraer_dia_y_hora_recepcion(fila_rec: dict) -> tuple:
            for col_f in ("fecha_recepcion", "created_at", "timestamp", "fecha"):
                raw_v = str(fila_rec.get(col_f) or "").strip()
                if raw_v and raw_v.upper() not in ("NONE", "NULL", ""):
                    try:
                        dt = datetime.fromisoformat(raw_v.replace("Z", "+00:00")).astimezone()
                        return (dt.strftime("%Y-%m-%d"), dt.strftime("%d-%m-%Y"), dt.strftime("%H:%M"))
                    except Exception:
                        parte_f = raw_v.replace("T", " ").split()[0].strip()
                        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                            try:
                                dt_p = datetime.strptime(parte_f, fmt)
                                return (dt_p.strftime("%Y-%m-%d"), dt_p.strftime("%d-%m-%Y"), "")
                            except ValueError:
                                continue
            return ("1900-01-01", "SIN FECHA", "")

        def seleccionar_dia_historico_rapido(dia_iso: str):
            dd_fecha_hist_rec.value = dia_iso
            txt_fecha_hist_rec.value = ""
            cargar_historico_recepciones()

        def limpiar_filtros_historico(e=None):
            txt_buscar_hist_rec.value = ""
            txt_fecha_hist_rec.value = ""
            dd_fecha_hist_rec.value = "TODAS"
            cargar_historico_recepciones()

        def descargar_pdf_historico_grupo(items_grupo: list, dia_cl: str, po_real_str: str):
            if not items_grupo:
                notificar("No hay registros en este grupo para generar el PDF.", "#D97706")
                return
            recepciones_raw = [x["raw"] if isinstance(x, dict) and "raw" in x else x for x in items_grupo]
            skus_grupo = {str(r.get("sku") or "").strip().upper() for r in recepciones_raw if r.get("sku")}
            mapa_desc, _ = consultar_maestra_por_skus(skus_grupo)

            primera = items_grupo[0] if isinstance(items_grupo[0], dict) else {}
            prov_str = primera.get("proveedor") or "RECEPCIÓN HISTÓRICA"
            raw_p = primera.get("raw") if "raw" in primera else primera
            cont_str = str(raw_p.get("contenedor") or primera.get("contenedor") or "N/A").strip()
            po_limpia = po_real_str.replace("PO ", "").replace("OC ", "").strip()

            cabecera_hist = {
                "codigo_asn": f"{po_real_str} (Recepción {dia_cl})",
                "numero_oc": po_limpia,
                "proveedor": prov_str,
                "estado": f"RECEPCIONADO EL {dia_cl}",
                "contenedor_referencia": cont_str,
                "fecha_cierre": f"{dia_cl} {primera.get('hora') or ''}".strip(),
            }

            agrupado_sku = {}
            for r in recepciones_raw:
                s_k = str(r.get("sku") or "").strip().upper()
                if not s_k:
                    continue
                unid_r = int(r.get("unidades_totales") or 0)
                cajas_r = int(r.get("cajas") or 0)
                if s_k not in agrupado_sku:
                    agrupado_sku[s_k] = {"unid": 0, "cajas": 0}
                agrupado_sku[s_k]["unid"] += unid_r
                agrupado_sku[s_k]["cajas"] += cajas_r

            filas_conc_hist = [
                {
                    "sku": s_k,
                    "descripcion": mapa_desc.get(s_k, "Ingreso Recepción"),
                    "cajas_esperadas": inf_s["cajas"],
                    "cajas_recibidas": inf_s["cajas"],
                    "unidades_esperadas": inf_s["unid"],
                    "unidades_recibidas": inf_s["unid"],
                    "diferencia": 0,
                    "dif_cajas": 0,
                    "estado": "VALIDADA",
                }
                for s_k, inf_s in sorted(agrupado_sku.items())
            ]

            try:
                ruta = generar_acta_pdf_completa(cabecera_hist, filas_conc_hist, recepciones_raw)
                descargar_archivo_web(ruta, f"Acta Histórica - {po_real_str} ({dia_cl})")
            except Exception as ex:
                notificar(f"Error generando PDF histórico: {ex}", "#B91C1C")

        def obtener_registros_seleccionados_hist() -> list:
            seleccionados = [reg for chk, reg in checks_hist_seleccionados.values() if chk.value]
            return seleccionados if seleccionados else list(ultimos_filtrados_hist)

        def marcar_desmarcar_hist(estado_bool: bool):
            for chk, _ in checks_hist_seleccionados.values():
                chk.value = estado_bool
            page.update()

        def filtrar_solo_sin_po_hist(e=None):
            txt_buscar_hist_rec.value = "SIN PO"
            cargar_historico_recepciones()

        def imprimir_lpns_seleccionados_hist(e=None):
            regs = obtener_registros_seleccionados_hist()
            if not regs:
                notificar("No hay artículos seleccionados o filtrados para imprimir.", "#D97706")
                return
            try:
                etiqueta_f = dd_fecha_hist_rec.value if dd_fecha_hist_rec.value != "TODAS" else "FILTRADOS"
                ruta = generar_pdf_masivo_lpns_po(f"SIN_PO_{etiqueta_f}", regs)
                descargar_archivo_web(ruta, f"Etiquetas 15x10 ({len(regs)} registros)")
            except Exception as ex:
                notificar(f"Error al generar LPNs seleccionados: {ex}", "#D91C1C")

        def exportar_excel_seleccionados_hist(e=None):
            regs = obtener_registros_seleccionados_hist()
            if not regs:
                notificar("No hay artículos seleccionados para bajar a Excel.", "#D97706")
                return
            try:
                os.makedirs("reportes_recepcion", exist_ok=True)
                filas_x = []
                for r in regs:
                    d_iso, d_cl, h_str = extraer_dia_y_hora_recepcion(r)
                    lote_c, qa_c = extraer_estado_qa(r.get("lote", "S/L"))
                    filas_x.append({
                        "Bodega": r.get("bodega") or obtener_bodega_actual(),
                        "Fecha_Recepcion": f"{d_cl} {h_str}".strip(),
                        "Contenedor_o_OC": r.get("contenedor") or (f"OC-{r.get('asn_id')}" if r.get("asn_id") else "SIN PO"),
                        "LPN": r.get("lpn"),
                        "SKU": r.get("sku"),
                        "Cajas": int(r.get("cajas") or 0),
                        "Multiplo": int(r.get("multiplo_aplicado") or 1),
                        "Unidades_Totales": int(r.get("unidades_totales") or 0),
                        "Lote": lote_c,
                        "Vencimiento": r.get("fecha_vencimiento_cl") or "S/F",
                        "Estado_QA": qa_c,
                    })
                df_h = pd.DataFrame(filas_x)
                ruta_x = os.path.join("reportes_recepcion", f"Recepciones_Filtradas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
                df_h.to_excel(ruta_x, index=False)
                descargar_archivo_web(ruta_x, "Excel Histórico de Recepciones")
            except Exception as ex:
                notificar(f"Error exportando Excel: {ex}", "#B91C1C")

        def descargar_pdf_historico_filtrado(e=None):
            regs_sel = obtener_registros_seleccionados_hist()
            if not regs_sel:
                notificar("No hay recepciones seleccionadas para descargar en PDF.", "#D97706")
                return
            dia_lbl = dd_fecha_hist_rec.value if (dd_fecha_hist_rec.value and dd_fecha_hist_rec.value != "TODAS") else datetime.now().strftime("%d-%m-%Y")
            descargar_pdf_historico_grupo(regs_sel, dia_lbl, "SELECCION")

        def cargar_historico_recepciones(e=None):
            nonlocal historico_filtrado_actual
            bodega_act = obtener_bodega_actual()
            filtro_h = (txt_buscar_hist_rec.value or "").strip().upper()
            filtro_fecha_txt = (txt_fecha_hist_rec.value or "").strip()
            dia_dropdown = dd_fecha_hist_rec.value or "TODAS"

            fecha_manual_iso = ""
            if filtro_fecha_txt:
                for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
                    try:
                        fecha_manual_iso = datetime.strptime(filtro_fecha_txt, fmt).strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue

            try:
                mapa_po_real = {}
                try:
                    res_cabs = supabase.table("asn_cabecera").select("*").limit(1000).execute()
                    for c in (res_cabs.data or []):
                        cid = str(c.get("id"))
                        num_po_limpio = obtener_nombre_po_cabecera(c)
                        mapa_po_real[cid] = {
                            "po_display": f"OC {num_po_limpio}" if num_po_limpio != "LIBRE" else "SIN PO",
                            "po_num": num_po_limpio,
                            "proveedor": str(c.get("proveedor") or "SIN PROVEEDOR").strip(),
                            "estado": str(c.get("estado") or "ACTIVO").strip().upper(),
                            "contenedor": str(c.get("contenedor_referencia") or "").strip(),
                            "bodega": str(c.get("bodega") or "Bodega Santiago").strip(),
                        }
                except Exception:
                    pass

                res_h = supabase.table("registro_recepcion").select("*").order("id", desc=True).limit(600).execute()
                filas_h_bodega = [r for r in (res_h.data or []) if coincide_bodega_fila(r, bodega_act)]

                registros_enriquecidos = []
                resumen_por_dia = {}
                resumen_dia_y_po = {}

                for r in filas_h_bodega:
                    dia_iso, dia_cl, hora_str = extraer_dia_y_hora_recepcion(r)
                    aid_str = str(r.get("asn_id")) if r.get("asn_id") is not None else ""
                    cont_rec = str(r.get("contenedor") or "").strip().upper()
                    cont_cab = ""

                    if aid_str and aid_str in mapa_po_real:
                        info_po = mapa_po_real[aid_str]
                        po_real_str = info_po["po_display"]
                        prov_str = info_po["proveedor"]
                        cont_cab = info_po["contenedor"]
                    elif cont_rec and not cont_rec.startswith("PO-") and not cont_rec.startswith("OC-"):
                        po_real_str = "SIN PO (LIBRE)"
                        prov_str = f"CONT: {cont_rec}"
                        cont_cab = cont_rec
                    else:
                        po_real_str = f"OC {formatear_nombre_po(cont_rec)}" if cont_rec else "SIN PO"
                        prov_str = "RECEPCIÓN DIRECTA"

                    lpn_h = str(r.get("lpn") or "-").strip()
                    sku_h = str(r.get("sku") or "-").strip()
                    unid_h = int(r.get("unidades_totales") or 0)
                    lote_c, qa_c = extraer_estado_qa(r.get("lote", "S/L"))

                    if dia_iso not in resumen_por_dia:
                        resumen_por_dia[dia_iso] = {"fecha_cl": dia_cl, "lpns": set(), "unid": 0, "pos": set()}
                    resumen_por_dia[dia_iso]["lpns"].add(lpn_h)
                    resumen_por_dia[dia_iso]["unid"] += unid_h
                    resumen_por_dia[dia_iso]["pos"].add(po_real_str)

                    clave_dp = (dia_iso, po_real_str)
                    if clave_dp not in resumen_dia_y_po:
                        resumen_dia_y_po[clave_dp] = {"dia_iso": dia_iso, "fecha_cl": dia_cl, "po": po_real_str, "lpns": set(), "unid": 0}
                    resumen_dia_y_po[clave_dp]["lpns"].add(lpn_h)
                    resumen_dia_y_po[clave_dp]["unid"] += unid_h

                    registros_enriquecidos.append({
                        "raw": r,
                        "dia_iso": dia_iso,
                        "dia_cl": dia_cl,
                        "hora": hora_str,
                        "po_real": po_real_str,
                        "proveedor": prov_str,
                        "contenedor": cont_rec or cont_cab or "N/A",
                        "lpn": lpn_h,
                        "sku": sku_h,
                        "lote": lote_c,
                        "qa": qa_c,
                    })

                opciones_dias = [opt_w("TODAS", "TODAS LAS FECHAS (SEPARADO POR DÍA)")]
                for d_iso in sorted(resumen_por_dia.keys(), reverse=True):
                    inf_d = resumen_por_dia[d_iso]
                    pos_txt = ", ".join(sorted(inf_d["pos"]))[:28]
                    opciones_dias.append(
                        opt_w(d_iso, f"📅 {inf_d['fecha_cl']} ({len(inf_d['lpns'])} LPNs | {pos_txt})")
                    )
                dd_fecha_hist_rec.options = opciones_dias
                if dia_dropdown not in [o.key for o in opciones_dias]:
                    dia_dropdown = "TODAS"
                    dd_fecha_hist_rec.value = "TODAS"

                fila_resumen_dias_hist.controls.clear()
                for (d_iso, po_s), inf_dp in sorted(resumen_dia_y_po.items(), key=lambda x: (x[0][0], x[0][1]), reverse=True)[:10]:
                    es_dia_sel = (dia_dropdown == d_iso)
                    fila_resumen_dias_hist.controls.append(
                        ft.Container(
                            padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                            bgcolor="#065F46" if es_dia_sel else "#181E20",
                            border_radius=6,
                            border=ft.Border.all(1, "#34D399" if es_dia_sel else BORDER_COLOR),
                            ink=True,
                            tooltip="Clic para filtrar este día de recepción",
                            on_click=lambda ev, d_k=d_iso: seleccionar_dia_historico_rapido(
                                "TODAS" if dd_fecha_hist_rec.value == d_k else d_k
                            ),
                            content=ft.Row(
                                [
                                    ft.Icon(ft.Icons.CALENDAR_MONTH_ROUNDED, color="#34D399", size=14),
                                    ft.Text(f"{inf_dp['fecha_cl']} • {po_s}", size=11, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                                    ft.Text(f"({len(inf_dp['lpns'])} LPNs | {inf_dp['unid']} UN)", size=10, color=ACCENT_CYAN),
                                ],
                                spacing=5,
                                tight=True,
                            ),
                        )
                    )

                filtrados = []
                for item in registros_enriquecidos:
                    if dia_dropdown != "TODAS" and item["dia_iso"] != dia_dropdown:
                        continue
                    if fecha_manual_iso and item["dia_iso"] != fecha_manual_iso:
                        continue
                    elif filtro_fecha_txt and not fecha_manual_iso and filtro_fecha_txt not in item["dia_cl"]:
                        continue
                    if filtro_h and not any(
                        filtro_h in campo.upper()
                        for campo in (item["lpn"], item["sku"], item["lote"], item["po_real"], item["proveedor"], item["dia_cl"])
                    ):
                        continue
                    filtrados.append(item)

                filtrados.sort(key=lambda x: (x["dia_iso"], x["po_real"], int(x["raw"].get("id") or 0)), reverse=True)
                historico_filtrado_actual = filtrados
                ultimos_filtrados_hist[:] = [x["raw"] for x in filtrados[:250]]

                tabla_historico_recepciones.rows.clear()
                checks_hist_seleccionados.clear()
                grupo_actual = None

                for item in filtrados[:250]:
                    r = item["raw"]
                    clave_grupo = (item["dia_cl"], item["po_real"])

                    if clave_grupo != grupo_actual:
                        grupo_actual = clave_grupo
                        lotes_grupo = [x for x in filtrados if (x["dia_cl"], x["po_real"]) == clave_grupo]
                        lpns_g_cnt = len({x["lpn"] for x in lotes_grupo})
                        unid_g_sum = sum(int(x["raw"].get("unidades_totales") or 0) for x in lotes_grupo)

                        tabla_historico_recepciones.rows.append(
                            ft.DataRow(
                                color="#1E293B",
                                cells=[
                                    ft.DataCell(ft.Icon(ft.Icons.CALENDAR_TODAY_ROUNDED, color="#34D399", size=14)),
                                    ft.DataCell(ft.Text(f"📅 DÍA: {item['dia_cl']}", weight=ft.FontWeight.W_900, size=11, color="#34D399")),
                                    ft.DataCell(ft.Text(item["po_real"], weight=ft.FontWeight.W_900, size=11, color="#FBBF24")),
                                    ft.DataCell(ft.Text(item["proveedor"][:24], weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                                    ft.DataCell(ft.Text(f"{lpns_g_cnt} LPNs en este día", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                                    ft.DataCell(ft.Text("-", size=10, color=TEXT_MUTED)),
                                    ft.DataCell(ft.Text("-", size=10, color=TEXT_MUTED)),
                                    ft.DataCell(ft.Text("-", size=10, color=TEXT_MUTED)),
                                    ft.DataCell(ft.Text(f"{unid_g_sum} UN recibidas", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                                    ft.DataCell(ft.Text("-", size=10, color=TEXT_MUTED)),
                                    ft.DataCell(ft.Text("-", size=10, color=TEXT_MUTED)),
                                    ft.DataCell(ft.Text("-", size=10, color=TEXT_MUTED)),
                                    ft.DataCell(
                                        boton_primario(
                                            "PDF RECEPCIÓN",
                                            ft.Icons.PICTURE_AS_PDF_OUTLINED,
                                            lambda ev, g_it=list(lotes_grupo), d_c=item["dia_cl"], p_r=item["po_real"]: descargar_pdf_historico_grupo(g_it, d_c, p_r),
                                            "#047857",
                                            height_val=26,
                                        )
                                    ),
                                ],
                            )
                        )

                    lpn_h = item["lpn"]
                    qa_c = item["qa"]
                    id_reg = r.get("id") or f"{lpn_h}_{item['sku']}"
                    chk_fila = ft.Checkbox(value=True, active_color=ACCENT_CYAN)
                    checks_hist_seleccionados[id_reg] = (chk_fila, r)

                    badge_qa = (
                        crear_badge_estado("APROBADO", "#065F46", "#D1FAE5")
                        if qa_c == "APROBADO"
                        else (
                            crear_badge_estado("CUARENTENA", "#92400E", "#FEF3C7")
                            if qa_c == "CUARENTENA"
                            else crear_badge_estado("RECHAZADO", "#991B1B", "#FEE2E2")
                        )
                    )
                    fecha_hora_mostrar = f"{item['dia_cl']} {item['hora']}".strip()

                    tabla_historico_recepciones.rows.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(chk_fila),
                                ft.DataCell(ft.Text(fecha_hora_mostrar, weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                                ft.DataCell(ft.Text(item["po_real"], weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(item["proveedor"][:22], size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(lpn_h, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN, size=11)),
                                ft.DataCell(ft.Text(item["sku"], weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(str(r.get("cajas", 0)), size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"x{r.get('multiplo_aplicado', 1)}", size=11, color=TEXT_MUTED)),
                                ft.DataCell(ft.Text(str(r.get("unidades_totales", 0)), weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(item["lote"], size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(str(r.get("fecha_vencimiento_cl") or "S/F"), size=11, color=TEXT_WHITE)),
                                ft.DataCell(badge_qa),
                                ft.DataCell(boton_primario("LPN 15x10", ft.Icons.PRINT_OUTLINED, lambda ev, cod=lpn_h: reimprimir_desde_fila(cod), ACCENT_TEAL, height_val=26)),
                            ]
                        )
                    )
                page.update()
            except Exception as ex:
                notificar(f"Error cargando histórico de recepciones: {ex}", "#B91C1C")

        def imprimir_todos_los_lpns_po_activa(e=None):
            auditar_asn_seleccionado()
            if not recepciones_asn_actual:
                notificar("No hay pallets (LPNs) registrados en esta OC para imprimir.", "#D97706")
                return
            try:
                cod_po = _nombre_archivo_seguro_local(obtener_nombre_po_cabecera(cabecera_asn_actual))
                ruta = generar_pdf_masivo_lpns_po(cod_po, recepciones_asn_actual)
                descargar_archivo_web(ruta, f"Etiquetas 15x10 LPNs - OC {cod_po}")
            except Exception as ex:
                notificar(f"Error al imprimir lote de LPNs: {ex}", "#B91C1C")

        def click_exportar_pdf_recepcion(e=None):
            auditar_asn_seleccionado()
            if not filas_conciliacion_export and not recepciones_asn_actual:
                notificar("No hay datos de recepción activos para exportar a PDF.", "#D97706")
                return
            try:
                ruta = generar_acta_pdf_completa(
                    cabecera_asn_actual,
                    filas_conciliacion_export,
                    recepciones_asn_actual,
                )
                cod_po = obtener_nombre_po_cabecera(cabecera_asn_actual)
                descargar_archivo_web(ruta, f"Acta Oficial de Recepción - OC {cod_po}")
            except Exception as ex:
                notificar(f"Error generando Acta PDF: {ex}", "#B91C1C")

        def enviar_correo_acta_po(e=None):
            """Genera el Acta PDF y abre Outlook vía win32com en Windows o enlace mailto: directo en SnackBar sin usar AlertDialog."""
            auditar_asn_seleccionado()
            if not filas_conciliacion_export and not recepciones_asn_actual:
                notificar("No hay datos de recepción activos para enviar por correo.", "#D97706")
                return
            try:
                ruta = generar_acta_pdf_completa(
                    cabecera_asn_actual,
                    filas_conciliacion_export,
                    recepciones_asn_actual,
                )
            except Exception as ex:
                notificar(f"Error generando PDF para correo: {ex}", "#B91C1C")
                return

            nombre_orig = os.path.basename(ruta)
            base_nom, ext_nom = os.path.splitext(nombre_orig)
            nombre_seguro = f"{_nombre_archivo_seguro_local(base_nom)}{ext_nom.lower()}"
            raiz_proyecto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            for carp in (os.path.join(os.getcwd(), "assets", "descargas"), os.path.join(raiz_proyecto, "assets", "descargas")):
                try:
                    os.makedirs(carp, exist_ok=True)
                    shutil.copy2(ruta, os.path.join(carp, nombre_seguro))
                except Exception:
                    pass
            url_pdf_web = f"/descargas/{urllib.parse.quote(nombre_seguro)}"

            cod_po_str = obtener_nombre_po_cabecera(cabecera_asn_actual)
            nota_asn = str(cabecera_asn_actual.get("codigo_asn") or "").strip()
            prov_str = str(cabecera_asn_actual.get("proveedor") or "PROVEEDOR").strip()
            cont_ref = str(cabecera_asn_actual.get("contenedor_referencia") or "").strip()

            tot_esp = sum(int(x.get("unidades_esperadas") or 0) for x in filas_conciliacion_export)
            tot_rec = sum(int(x.get("unidades_recibidas") or 0) for x in filas_conciliacion_export)
            dif_tot = tot_rec - tot_esp

            resumen_skus = []
            for f in filas_conciliacion_export[:25]:
                resumen_skus.append(
                    f"- {f.get('sku')}: OC {f.get('unidades_esperadas', 0)} UN | Recibido {f.get('unidades_recibidas', 0)} UN ({f.get('estado', '')})"
                )

            asunto_default = f"Acta de Recepción - OC {cod_po_str} ({prov_str}) | LUDIPEK WMS"
            cuerpo_default = (
                f"Estimado equipo,\n\n"
                f"Se informa la recepción de la Orden de Compra N° {cod_po_str} ({nota_asn}) en LUDIPEK WMS ({obtener_bodega_actual()}):\n\n"
                f"• Proveedor: {prov_str}\n"
                + (f"• Contenedor / Guía: {cont_ref}\n" if cont_ref else "")
                + f"• Total Unidades OC: {tot_esp} UN  |  Total Físico Recibido: {tot_rec} UN (Dif: {dif_tot:+d} UN)\n\n"
                f"Resumen por SKU:\n" + "\n".join(resumen_skus) + "\n\n"
                f"Saludos cordiales,\nTorre de Control LUDIPEK WMS"
            )

            # 1. Intentar abrir Outlook local con el PDF adjunto si corre en Windows
            if os.name == "nt":
                try:
                    import pythoncom
                    import win32com.client as win32
                    pythoncom.CoInitialize()
                    outlook = win32.Dispatch("outlook.application")
                    mail = outlook.CreateItem(0)
                    mail.To = "compras@ludipek.cl; logistica@ludipek.cl"
                    mail.Subject = asunto_default
                    mail.Body = cuerpo_default
                    mail.Attachments.Add(os.path.abspath(ruta))
                    mail.Display(False)
                    notificar(f"Borrador de Outlook abierto con el Acta PDF de OC {cod_po_str} adjunta.", "#047857")
                    return
                except Exception:
                    pass

            # 2. Respaldo Web/Cloud sin AlertDialog: SnackBar con botones directos de correo mailto: y descarga PDF
            mailto_url = (
                f"mailto:compras@ludipek.cl,logistica@ludipek.cl"
                f"?subject={urllib.parse.quote(asunto_default)}"
                f"&body={urllib.parse.quote(cuerpo_default)}"
            )
            snack_mail = ft.SnackBar(
                bgcolor="#0F172A",
                duration=10000,
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.MARK_EMAIL_READ_ROUNDED, color="#38BDF8", size=20),
                        ft.Text(
                            f"Acta OC {cod_po_str} lista para enviar:",
                            color=ft.Colors.WHITE,
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            expand=True,
                        ),
                        ft.TextButton(
                            content=ft.Text("1. BAJAR ACTA PDF", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                            url=url_pdf_web,
                            style=ft.ButtonStyle(bgcolor=ACCENT_TEAL, padding=ft.Padding.symmetric(horizontal=10, vertical=6)),
                        ),
                        ft.TextButton(
                            content=ft.Text("2. ABRIR CORREO", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                            url=mailto_url,
                            style=ft.ButtonStyle(bgcolor="#047857", padding=ft.Padding.symmetric(horizontal=10, vertical=6)),
                        ),
                    ],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            )
            self.page.show_dialog(snack_mail)
            self.page.update()

        def click_exportar_excel_recepcion(e=None):
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

            auditar_asn_seleccionado()
            if not filas_conciliacion_export and not recepciones_asn_actual:
                notificar("No hay datos de recepción activos para exportar a Excel.", "#D97706")
                return
            try:
                skus_excel_set = {str(r.get("sku") or "").strip().upper() for r in recepciones_asn_actual if r.get("sku")}
                skus_excel_set.update({str(f.get("sku") or "").strip().upper() for f in filas_conciliacion_export if f.get("sku")})
                mapa_desc, mapa_mult = consultar_maestra_por_skus(skus_excel_set)

                mapa_conc = {}
                for f in filas_conciliacion_export:
                    s_f = str(f.get("sku", "")).strip().upper()
                    if s_f:
                        mapa_conc[s_f] = f
                    if s_f and not mapa_desc.get(s_f):
                        mapa_desc[s_f] = str(f.get("descripcion") or "Ingreso Directo")
                    if s_f and s_f not in mapa_mult:
                        mapa_mult[s_f] = max(1, int(f.get("multiplo") or 1))

                agrupado_excel = {}
                for r in recepciones_asn_actual:
                    sku_r = str(r.get("sku", "")).strip().upper()
                    if not sku_r:
                        continue
                    lote_limpio, _ = extraer_estado_qa(r.get("lote", "S/L"))
                    fecha_raw = str(r.get("fecha_vencimiento_cl") or "").strip()
                    fecha_fmt = normalizar_fecha_sql(fecha_raw) or "S/F"
                    cajas_r = int(r.get("cajas") or 0)
                    unid_r = int(r.get("unidades_totales") or 0)

                    clave = (sku_r, lote_limpio, fecha_fmt)
                    if clave not in agrupado_excel:
                        agrupado_excel[clave] = {"packs": 0, "unidades": 0}
                    agrupado_excel[clave]["packs"] += cajas_r
                    agrupado_excel[clave]["unidades"] += unid_r

                filas_lotes = []
                for (sku_k, lote_k, fecha_k), totales in sorted(agrupado_excel.items(), key=lambda x: (x[0][0], x[0][1])):
                    unid_tot, packs_tot = totales["unidades"], totales["packs"]
                    if packs_tot == 0 and unid_tot > 0:
                        packs_tot = unid_tot // mapa_mult.get(sku_k, 1) if mapa_mult.get(sku_k, 1) > 1 else unid_tot
                    lote_fecha_str = (
                        f"{lote_k} - {fecha_k}"
                        if (lote_k != "S/L" and fecha_k != "S/F")
                        else (lote_k if lote_k != "S/L" else fecha_k)
                    )
                    inf_c = mapa_conc.get(sku_k, {})
                    est_k = str(inf_c.get("estado") or "VALIDADA")
                    dif_cj = int(inf_c.get("dif_cajas") or 0)
                    if est_k == "SKU FUERA DE OC":
                        est_mostrar = "FUERA DE OC (NO PEDIDO)"
                    elif est_k == "SOBRANTE":
                        est_mostrar = f"SOBRANTE ({dif_cj:+d} CJ)"
                    elif est_k == "PARCIAL":
                        est_mostrar = f"PARCIAL ({dif_cj:+d} CJ)"
                    else:
                        est_mostrar = "OK (VALIDADA)"

                    filas_lotes.append({
                        "sku": sku_k,
                        "descripcion": mapa_desc.get(sku_k, "Ingreso Directo"),
                        "packs": packs_tot,
                        "lote": lote_k,
                        "lote_fecha": lote_fecha_str,
                        "fecha": fecha_k,
                        "unidades": unid_tot,
                        "estatus": est_mostrar,
                        "es_alerta": est_k in ("SKU FUERA DE OC", "SOBRANTE"),
                    })

                if not filas_lotes and filas_conciliacion_export:
                    for f in filas_conciliacion_export:
                        sku_f = str(f.get("sku", "")).strip().upper()
                        filas_lotes.append({
                            "sku": sku_f,
                            "descripcion": mapa_desc.get(sku_f, str(f.get("descripcion", ""))),
                            "packs": int(f.get("cajas_recibidas") or f.get("cajas_esperadas") or 0),
                            "lote": str(f.get("lotes_reales") or "S/L"),
                            "lote_fecha": str(f.get("lotes_reales") or "S/L"),
                            "fecha": "S/F",
                            "unidades": int(f.get("unidades_recibidas") or f.get("unidades_esperadas") or 0),
                            "estatus": str(f.get("estado") or "PENDIENTE"),
                            "es_alerta": False,
                        })

                codigo_po_raw = str(cabecera_asn_actual.get("numero_oc") or cabecera_asn_actual.get("codigo_asn") or "LIBRE").strip()
                prov_str = str(cabecera_asn_actual.get("proveedor") or "RECEPCION DIRECTA").strip()
                nota_str = str(cabecera_asn_actual.get("codigo_asn") or "").strip()
                cont_str = str(cabecera_asn_actual.get("contenedor_referencia") or "N/A").strip()
                ahora_fmt = datetime.now().strftime("%d-%m-%Y %H:%M")

                os.makedirs("reportes_recepcion", exist_ok=True)
                codigo_po = _nombre_archivo_seguro_local(codigo_po_raw)
                nombre_archivo = os.path.join(
                    "reportes_recepcion",
                    f"Reporte_Recepcion_OC_{codigo_po}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                )

                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Acta_Recepcion"

                ruta_logo = _buscar_ruta_logo_ludipek()
                logo_insertado = False
                if ruta_logo:
                    try:
                        from openpyxl.drawing.image import Image as OpenpyxlImage
                        img_xl = OpenpyxlImage(ruta_logo)
                        img_xl.width = 72
                        img_xl.height = 72
                        ws.add_image(img_xl, "A1")
                        logo_insertado = True
                    except Exception:
                        logo_insertado = False

                if not logo_insertado:
                    ws["A1"] = "LUDIPEK WMS"
                    ws["A1"].font = Font(name="Calibri", size=18, bold=True, color="1E3A8A")

                ws.row_dimensions[1].height = 22
                ws.row_dimensions[2].height = 18
                ws.row_dimensions[3].height = 18

                ws["B1"] = f"LUDIPEK WMS - ACTA OFICIAL DE RECEPCIÓN (OC: {codigo_po_raw})"
                ws["B1"].font = Font(name="Calibri", size=15, bold=True, color="0F172A")

                ws["B2"] = f"Proveedor: {prov_str}   |   Referencia / Nota: {nota_str}   |   Bodega: {obtener_bodega_actual()}"
                ws["B2"].font = Font(name="Calibri", size=11, bold=True, color="334155")

                ws["B3"] = f"Contenedor / Guía: {cont_str}   |   Fecha de Emisión: {ahora_fmt}"
                ws["B3"].font = Font(name="Calibri", size=10, italic=True, color="64748B")

                encabezados = [
                    "SKU",
                    "Descripción del Producto",
                    "Cantidad (Pack / Cj)",
                    "Lote Físico",
                    "LOTE - FECHA",
                    "Fecha Vencimiento",
                    "Cantidad (Unidades)",
                    "Estatus Conciliación OC",
                ]
                fill_hdr = PatternFill(fill_type="solid", start_color="1E3A8A", end_color="1E3A8A")
                fill_zebra = PatternFill(fill_type="solid", start_color="F8FAFC", end_color="F8FAFC")
                fill_alerta = PatternFill(fill_type="solid", start_color="FEE2E2", end_color="FEE2E2")
                fill_total = PatternFill(fill_type="solid", start_color="E2E8F0", end_color="E2E8F0")
                font_hdr = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                borde_fino = Side(style="thin", color="CBD5E1")
                border_celda = Border(left=borde_fino, right=borde_fino, top=borde_fino, bottom=borde_fino)

                ws.row_dimensions[5].height = 24
                for col_idx, texto_h in enumerate(encabezados, start=1):
                    c = ws.cell(row=5, column=col_idx, value=texto_h)
                    c.fill = fill_hdr
                    c.font = font_hdr
                    c.alignment = Alignment(horizontal="center", vertical="center")
                    c.border = border_celda

                tot_packs = 0
                tot_unidades = 0
                fila_actual = 6

                for idx_f, item in enumerate(filas_lotes):
                    tot_packs += int(item["packs"])
                    tot_unidades += int(item["unidades"])
                    es_alerta = bool(item.get("es_alerta"))
                    valores = [
                        item["sku"],
                        item["descripcion"],
                        int(item["packs"]),
                        item["lote"],
                        item["lote_fecha"],
                        item["fecha"],
                        int(item["unidades"]),
                        item["estatus"],
                    ]
                    ws.row_dimensions[fila_actual].height = 20
                    for c_idx, val in enumerate(valores, start=1):
                        celda = ws.cell(row=fila_actual, column=c_idx, value=val)
                        celda.font = Font(
                            name="Calibri",
                            size=11,
                            bold=(c_idx in (1, 7, 8) or es_alerta),
                            color="991B1B" if es_alerta else "000000",
                        )
                        celda.border = border_celda
                        if es_alerta:
                            celda.fill = fill_alerta
                        elif idx_f % 2 == 1:
                            celda.fill = fill_zebra
                        if c_idx in (1, 3, 4, 5, 6, 7, 8):
                            celda.alignment = Alignment(horizontal="center", vertical="center")
                        else:
                            celda.alignment = Alignment(horizontal="left", vertical="center")
                    fila_actual += 1

                ws.row_dimensions[fila_actual].height = 22
                ws.cell(row=fila_actual, column=1, value="TOTAL").alignment = Alignment(horizontal="center", vertical="center")
                ws.cell(row=fila_actual, column=2, value="TOTAL FÍSICO RECIBIDO").alignment = Alignment(horizontal="right", vertical="center")
                ws.cell(row=fila_actual, column=3, value=tot_packs).alignment = Alignment(horizontal="center", vertical="center")
                ws.cell(row=fila_actual, column=4, value="-").alignment = Alignment(horizontal="center", vertical="center")
                ws.cell(row=fila_actual, column=5, value="-").alignment = Alignment(horizontal="center", vertical="center")
                ws.cell(row=fila_actual, column=6, value="-").alignment = Alignment(horizontal="center", vertical="center")
                ws.cell(row=fila_actual, column=7, value=tot_unidades).alignment = Alignment(horizontal="center", vertical="center")
                ws.cell(row=fila_actual, column=8, value="").alignment = Alignment(horizontal="center", vertical="center")

                for c_i in range(1, 9):
                    c_tot = ws.cell(row=fila_actual, column=c_i)
                    c_tot.font = Font(name="Calibri", size=11, bold=True, color="0F172A")
                    c_tot.fill = fill_total
                    c_tot.border = border_celda

                anchos = {"A": 16, "B": 44, "C": 20, "D": 18, "E": 24, "F": 18, "G": 20, "H": 26}
                for col_l, w_val in anchos.items():
                    ws.column_dimensions[col_l].width = w_val

                try:
                    wb.save(nombre_archivo)
                except Exception:
                    ws._images.clear()
                    ws["A1"] = "LUDIPEK WMS"
                    ws["A1"].font = Font(name="Calibri", size=16, bold=True, color="1E3A8A")
                    wb.save(nombre_archivo)

                descargar_archivo_web(nombre_archivo, f"Excel Oficial de Recepción - OC {codigo_po_raw}")
            except Exception as ex:
                notificar(f"Error generando Excel: {ex}", "#B91C1C")

        def exportar_csv_recepcion_netsuite(e=None) -> str:
            auditar_asn_seleccionado()
            if not filas_conciliacion_export and not recepciones_asn_actual:
                notificar("No hay datos para generar el CSV.", "#D97706")
                return ""
            os.makedirs("reportes_recepcion", exist_ok=True)
            oc_actual = str(cabecera_asn_actual.get("numero_oc") or "").strip()
            cod_po = _nombre_archivo_seguro_local(cabecera_asn_actual.get("codigo_asn", "SIN-OC"))
            if not oc_actual or oc_actual == "S/OC":
                oc_actual = cod_po.removeprefix("PO-").removeprefix("OC-").removeprefix("ASN-").strip()

            recibido_por_sku = {}
            for r in recepciones_asn_actual:
                sku_r = str(r.get("sku", "")).strip().upper()
                unid_r = int(r.get("unidades_totales") or 0)
                if sku_r and unid_r > 0:
                    recibido_por_sku[sku_r] = recibido_por_sku.get(sku_r, 0) + unid_r

            if not recibido_por_sku:
                notificar("0 unidades físicas recibidas.", "#D97706")
                return ""

            oc_limpia = _nombre_archivo_seguro_local(oc_actual)
            ruta_meta_ns = os.path.join("reportes_recepcion", f"ns_meta_{oc_limpia}.json")
            if not os.path.exists(ruta_meta_ns):
                ruta_meta_ns = os.path.join("reportes_recepcion", f"ns_meta_PO-{oc_limpia}.json")

            meta_lineas_ns = []
            if os.path.exists(ruta_meta_ns):
                try:
                    with open(ruta_meta_ns, "r", encoding="utf-8") as f_m:
                        meta_lineas_ns = json.load(f_m)
                except Exception:
                    pass

            id_asn_sufijo = str(asn_actual_id or datetime.now().strftime("%H%M"))
            external_id_unico = f"REC-{oc_actual or 'LIBRE'}-{id_asn_sufijo}"
            fecha_contable = datetime.now().strftime("%d/%m/%Y")
            bodega_default = (txt_ns_location_id.value or "1").strip()

            filas_csv = []
            restante_por_sku = dict(recibido_por_sku)
            if meta_lineas_ns:
                conteo_lineas_sku = {}
                for m in meta_lineas_ns:
                    conteo_lineas_sku[m["sku"]] = conteo_lineas_sku.get(m["sku"], 0) + 1
                vistos_sku = {}
                for linea_ns in meta_lineas_ns:
                    sku_ns = linea_ns["sku"]
                    disponible = restante_por_sku.get(sku_ns, 0)
                    if disponible <= 0:
                        continue
                    vistos_sku[sku_ns] = vistos_sku.get(sku_ns, 0) + 1
                    cant_asignada = disponible if vistos_sku[sku_ns] == conteo_lineas_sku[sku_ns] else min(disponible, int(linea_ns.get("cantidad_esperada") or disponible))
                    restante_por_sku[sku_ns] -= cant_asignada
                    if cant_asignada > 0:
                        filas_csv.append(
                            {
                                "external_id": external_id_unico,
                                "po_internal_id": linea_ns["po_internal_id"],
                                "po_line_num": linea_ns["po_line_num"],
                                "item_id": linea_ns["item_id"],
                                "qty_received": cant_asignada,
                                "location_id": linea_ns.get("location_id") or bodega_default,
                                "trandate": fecha_contable,
                            }
                        )

            for idx_f, (sku_pend, cant_pend) in enumerate(restante_por_sku.items(), start=1):
                if cant_pend > 0:
                    filas_csv.append(
                        {
                            "external_id": external_id_unico,
                            "po_internal_id": str(oc_actual or asn_actual_id or ""),
                            "po_line_num": str(idx_f),
                            "item_id": sku_pend,
                            "qty_received": cant_pend,
                            "location_id": bodega_default,
                            "trandate": fecha_contable,
                        }
                    )

            df_csv_ns = pd.DataFrame(filas_csv, columns=["external_id", "po_internal_id", "po_line_num", "item_id", "qty_received", "location_id", "trandate"])
            ruta_csv = os.path.join("reportes_recepcion", f"NetSuite_ItemReceipt_{cod_po}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            df_csv_ns.to_csv(ruta_csv, index=False, encoding="utf-8-sig")
            descargar_archivo_web(ruta_csv, f"CSV Item Receipt NetSuite - OC {cod_po}")
            return ruta_csv

        def descargar_po_netsuite_inbound(e=None):
            oc_input = (txt_po_netsuite.value or "").strip().upper()
            if not oc_input:
                notificar("Ingrese el N° de Orden de Compra (Ej: 2043) para consultar en NetSuite.", "#D97706")
                return

            oc_num_limpio = oc_input.replace("OC-", "").replace("PO-", "").replace("OC", "").strip()

            if not NETSUITE_CONECTADO:
                notificar("Módulo conexion_erp no activo. Verifique credenciales de NetSuite.", "#D97706")
                return

            notificar(f"Consultando Orden de Compra N° {oc_num_limpio} en NetSuite...", ACCENT_CYAN)

            q_po = f"""
                SELECT
                    t.id AS po_internal_id,
                    t.tranid AS numero_oc,
                    t.memo AS nota_po,
                    TO_CHAR(t.trandate, 'YYYY-MM-DD') AS fecha_oc,
                    BUILTIN.DF(t.entity) AS proveedor,
                    BUILTIN.DF(t.status) AS estado_ns,
                    i.itemid AS sku,
                    BUILTIN.DF(tl.item) AS descripcion,
                    ABS(tl.quantity) AS cantidad
                FROM transaction t
                INNER JOIN transactionline tl ON t.id = tl.transaction
                INNER JOIN item i ON tl.item = i.id
                WHERE t.type = 'PurchOrd'
                AND tl.mainline = 'F'
                AND (
                    UPPER(TRIM(t.tranid)) = '{oc_num_limpio}'
                    OR UPPER(TRIM(t.tranid)) = 'OC{oc_num_limpio}'
                    OR UPPER(t.memo) LIKE '%{oc_input}%'
                )
                ORDER BY i.itemid ASC
            """
            try:
                df_po = consultar_netsuite(q_po)
            except Exception as ex_ns:
                notificar(f"Error consultando NetSuite: {ex_ns}", "#B91C1C")
                return

            if df_po is None or df_po.empty:
                notificar(f"No se encontró la Orden de Compra '{oc_input}' en NetSuite.", "#D97706")
                return

            primera_fila = df_po.iloc[0]
            num_oc_real = str(primera_fila.get("numero_oc") or oc_num_limpio).strip().upper()
            raw_nota = primera_fila.get("nota_po")
            nota_po_str = "" if (raw_nota is None or str(raw_nota).strip().upper() in ("NONE", "NULL", "NAN")) else str(raw_nota).strip()
            proveedor_str = str(primera_fila.get("proveedor") or "PROVEEDOR SIN NOMBRE").strip()
            fecha_oc_str = str(primera_fila.get("fecha_oc") or datetime.now().strftime("%Y-%m-%d")).strip()
            estado_ns_str = str(primera_fila.get("estado_ns") or "ABIERTA").strip()

            skus_ns_set = {str(r.get("sku") or "").strip().upper() for _, r in df_po.iterrows() if r.get("sku")}
            mapa_desc_maestra, mapa_multiplos = consultar_maestra_por_skus(skus_ns_set)

            skus_agrupados = {}
            for _, row in df_po.iterrows():
                sku_c = str(row.get("sku") or "").strip().upper()
                if not sku_c or sku_c in ("NONE", "NULL"):
                    continue
                cant_u = int(float(row.get("cantidad") or 0))
                if cant_u <= 0:
                    continue
                desc_c = mapa_desc_maestra.get(sku_c) or str(row.get("descripcion") or sku_c).strip()
                mult_c = mapa_multiplos.get(sku_c, 1)

                if sku_c not in skus_agrupados:
                    skus_agrupados[sku_c] = {
                        "sku": sku_c,
                        "descripcion": desc_c,
                        "unidades_esperadas": 0,
                        "multiplo": mult_c,
                    }
                skus_agrupados[sku_c]["unidades_esperadas"] += cant_u

            lista_lineas_po = list(skus_agrupados.values())
            if not lista_lineas_po:
                notificar(f"La OC {num_oc_real} no contiene líneas de artículos válidas.", "#D97706")
                return

            total_skus = len(lista_lineas_po)
            total_unidades = sum(x["unidades_esperadas"] for x in lista_lineas_po)

            filas_preview = []
            for item_p in lista_lineas_po:
                cajas_est = max(1, round(item_p["unidades_esperadas"] / item_p["multiplo"]))
                filas_preview.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(item_p["sku"], weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(item_p["descripcion"][:38], size=11, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(f"x{item_p['multiplo']}", size=11, color=TEXT_MUTED)),
                            ft.DataCell(ft.Text(f"{cajas_est} Cj", size=11, color="#FBBF24")),
                            ft.DataCell(ft.Text(f"{item_p['unidades_esperadas']} UN", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                        ]
                    )
                )

            tabla_preview_po = ft.DataTable(
                heading_row_color="#0F172A",
                heading_row_height=32,
                data_row_min_height=28,
                data_row_max_height=34,
                column_spacing=14,
                columns=[
                    ft.DataColumn(ft.Text("SKU", size=10, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN)),
                    ft.DataColumn(ft.Text("DESCRIPCIÓN", size=10, weight=ft.FontWeight.BOLD, color=TEXT_WHITE)),
                    ft.DataColumn(ft.Text("MÚLT.", size=10, weight=ft.FontWeight.BOLD, color=TEXT_MUTED)),
                    ft.DataColumn(ft.Text("CAJAS EST.", size=10, weight=ft.FontWeight.BOLD, color="#FBBF24")),
                    ft.DataColumn(ft.Text("UNIDADES", size=10, weight=ft.FontWeight.BOLD, color="#34D399")),
                ],
                rows=filas_preview,
            )

            def cerrar_modal_po():
                try:
                    page.pop_dialog()
                except Exception:
                    dlg_confirmar_po.open = False
                page.update()

            def confirmar_uso_po(ev):
                cerrar_modal_po()
                try:
                    cod_asn = f"OC-{num_oc_real} | {nota_po_str}" if nota_po_str else f"OC-{num_oc_real}"
                    bodega_usr = obtener_bodega_actual()

                    res_ex = (
                        supabase.table("asn_cabecera")
                        .select("id")
                        .or_(f"numero_oc.eq.{num_oc_real},codigo_asn.ilike.OC-{num_oc_real}%")
                        .limit(1)
                        .execute()
                    )
                    if res_ex.data:
                        asn_id_nuevo = res_ex.data[0]["id"]
                        try:
                            supabase.table("asn_cabecera").update({
                                "codigo_asn": cod_asn,
                                "numero_oc": num_oc_real,
                                "proveedor": proveedor_str,
                                "estado": "EN_RECEPCION",
                                "bodega": bodega_usr,
                            }).eq("id", asn_id_nuevo).execute()
                        except Exception:
                            supabase.table("asn_cabecera").update({
                                "codigo_asn": cod_asn,
                                "numero_oc": num_oc_real,
                                "proveedor": proveedor_str,
                                "estado": "EN_RECEPCION",
                            }).eq("id", asn_id_nuevo).execute()
                    else:
                        payload_base = {
                            "codigo_asn": cod_asn,
                            "numero_oc": num_oc_real,
                            "proveedor": proveedor_str,
                            "estado": "EN_RECEPCION",
                        }
                        try:
                            res_ins = supabase.table("asn_cabecera").insert({
                                **payload_base,
                                "fecha_documento": fecha_oc_str,
                                "bodega": bodega_usr,
                            }).execute()
                        except Exception:
                            try:
                                res_ins = supabase.table("asn_cabecera").insert({
                                    **payload_base,
                                    "fecha_documento": fecha_oc_str,
                                }).execute()
                            except Exception:
                                res_ins = supabase.table("asn_cabecera").insert(payload_base).execute()
                        asn_id_nuevo = res_ins.data[0]["id"]

                    res_det_ex = supabase.table("asn_detalle").select("sku").eq("asn_id", asn_id_nuevo).execute()
                    skus_ya_en_bd = {str(r.get("sku") or "").strip().upper() for r in (res_det_ex.data or [])}

                    nuevas_lineas_bd = []
                    for item_p in lista_lineas_po:
                        if item_p["sku"] not in skus_ya_en_bd:
                            cajas_esp = max(1, round(item_p["unidades_esperadas"] / item_p["multiplo"]))
                            nuevas_lineas_bd.append({
                                "asn_id": asn_id_nuevo,
                                "sku": item_p["sku"],
                                "descripcion_proveedor": item_p["descripcion"],
                                "cajas_esperadas": cajas_esp,
                                "multiplo_empaque": item_p["multiplo"],
                                "unidades_esperadas": item_p["unidades_esperadas"],
                                "lote_sugerido": "S/L",
                            })
                    if nuevas_lineas_bd:
                        supabase.table("asn_detalle").insert(nuevas_lineas_bd).execute()

                    cargar_lista_asns()
                    dd_asn.value = str(asn_id_nuevo)
                    auditar_asn_seleccionado()
                    txt_nota_notif = f" (Nota/PO: {nota_po_str})" if nota_po_str else ""
                    notificar(f"Orden de Compra {num_oc_real}{txt_nota_notif} activada para recepción en {bodega_usr}.", "#047857")
                except Exception as ex_save:
                    notificar(f"Error al activar OC {num_oc_real}: {ex_save}", "#B91C1C")

            dlg_confirmar_po = ft.AlertDialog(
                modal=True,
                bgcolor="#1E293B",
                title=ft.Row(
                    [
                        ft.Icon(ft.Icons.FACT_CHECK_ROUNDED, color=ACCENT_CYAN, size=24),
                        ft.Text(
                            f"¿Utilizar Orden de Compra N° {num_oc_real}?" + (f" ({nota_po_str})" if nota_po_str else ""),
                            size=16,
                            weight=ft.FontWeight.BOLD,
                            color=TEXT_WHITE,
                        ),
                    ],
                    spacing=8,
                ),
                content=ft.Container(
                    width=680,
                    height=390,
                    content=ft.Column(
                        [
                            ft.Container(
                                padding=12,
                                bgcolor="#0F172A",
                                border_radius=8,
                                border=ft.Border.all(1, ACCENT_CYAN),
                                content=ft.Column(
                                    [
                                        ft.Text(f"PROVEEDOR: {proveedor_str}", size=14, weight=ft.FontWeight.W_900, color="#34D399"),
                                        ft.Text(
                                            f"N° ORDEN DE COMPRA (Rige en WMS): {num_oc_real}   |   NOTA / PO ASOCIADA: {nota_po_str or 'SIN NOTA'}",
                                            size=12,
                                            weight=ft.FontWeight.BOLD,
                                            color=ACCENT_CYAN,
                                        ),
                                        ft.Text(
                                            f"Fecha OC: {fecha_oc_str}   |   Estado NetSuite: {estado_ns_str}   |   Bodega: {obtener_bodega_actual()}",
                                            size=11,
                                            color=TEXT_WHITE,
                                        ),
                                        ft.Text(
                                            f"Resumen de Carga: {total_skus} SKUs distintos   |   Total a Recibir: {total_unidades} Unidades",
                                            size=12,
                                            weight=ft.FontWeight.BOLD,
                                            color="#FBBF24",
                                        ),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            ft.Text("DETALLE DE SKUs CONTENIDOS EN LA ORDEN DE COMPRA:", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
                            ft.Container(
                                expand=True,
                                bgcolor="#181E20",
                                border_radius=6,
                                border=ft.Border.all(1, BORDER_COLOR),
                                content=ft.Column([tabla_preview_po], scroll=ft.ScrollMode.AUTO),
                            ),
                        ],
                        spacing=10,
                    ),
                ),
                actions=[
                    ft.TextButton("CANCELAR", on_click=lambda e: cerrar_modal_po()),
                    boton_primario(
                        f"SÍ, UTILIZAR OC {num_oc_real}",
                        ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                        confirmar_uso_po,
                        "#047857",
                        height_val=36,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )

            page.show_dialog(dlg_confirmar_po)
            page.update()

        def abrir_gestor_limpieza_ocs_admin(e=None):
            rol_usr = str(getattr(self.page, "rol_actual", "")).upper()
            if "ADMIN" not in rol_usr:
                notificar("Acción restringida: solo un usuario Administrador puede cerrar o eliminar OCs.", "#B91C1C")
                return

            try:
                bodega_act = obtener_bodega_actual()
                res_act = supabase.table("asn_cabecera").select("*").neq("estado", "COMPLETADO").order("id", desc=True).execute()
                lista_ocs = [r for r in (res_act.data or []) if coincide_bodega_fila(r, bodega_act)]
            except Exception as ex:
                notificar(f"Error consultando OCs activas: {ex}", "#B91C1C")
                return

            if not lista_ocs:
                notificar(f"No hay órdenes abiertas pendientes por limpiar en {obtener_bodega_actual()}.", "#047857")
                return

            checks_admin_oc = {}
            filas_admin = []

            for r in lista_ocs:
                id_oc = r["id"]
                num_oc = str(r.get("numero_oc") or "-").strip()
                cod_asn = str(r.get("codigo_asn") or "-").strip()
                prov = str(r.get("proveedor") or "-").strip()
                est = str(r.get("estado") or "ACTIVO").strip()

                chk = ft.Checkbox(value=(str(id_oc) == str(dd_asn.value)), active_color=ACCENT_CYAN)
                checks_admin_oc[id_oc] = chk

                filas_admin.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(chk),
                            ft.DataCell(ft.Text(str(id_oc), size=11, color=TEXT_MUTED)),
                            ft.DataCell(ft.Text(f"OC {num_oc}", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(cod_asn[:28], size=11, color="#FBBF24")),
                            ft.DataCell(ft.Text(prov[:28], size=11, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(est, size=11, color="#34D399")),
                        ]
                    )
                )

            tabla_limpieza_admin = ft.DataTable(
                heading_row_color="#0F172A",
                heading_row_height=32,
                data_row_min_height=30,
                data_row_max_height=36,
                column_spacing=14,
                columns=[
                    ft.DataColumn(ft.Text("SEL.", size=10, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN)),
                    ft.DataColumn(ft.Text("ID", size=10, weight=ft.FontWeight.BOLD, color=TEXT_MUTED)),
                    ft.DataColumn(ft.Text("N° OC", size=10, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN)),
                    ft.DataColumn(ft.Text("NOTA / PO", size=10, weight=ft.FontWeight.BOLD, color="#FBBF24")),
                    ft.DataColumn(ft.Text("PROVEEDOR", size=10, weight=ft.FontWeight.BOLD, color=TEXT_WHITE)),
                    ft.DataColumn(ft.Text("ESTADO", size=10, weight=ft.FontWeight.BOLD, color=TEXT_WHITE)),
                ],
                rows=filas_admin,
            )

            def cerrar_dlg_admin():
                try:
                    page.pop_dialog()
                except Exception:
                    dlg_admin_ocs.open = False
                page.update()

            def cerrar_seleccionadas_admin(ev):
                ids_sel = [k for k, c in checks_admin_oc.items() if c.value]
                if not ids_sel:
                    notificar("Marque al menos una OC para cerrarla.", "#D97706")
                    return
                try:
                    for id_k in ids_sel:
                        supabase.table("asn_cabecera").update({"estado": "COMPLETADO"}).eq("id", id_k).execute()
                    cerrar_dlg_admin()
                    dd_asn.value = None
                    cargar_lista_asns()
                    cargar_historico_recepciones()
                    notificar(f"{len(ids_sel)} OC(s) cerradas y quitadas del panel activo.", "#047857")
                except Exception as ex_c:
                    notificar(f"Error cerrando OCs: {ex_c}", "#B91C1C")

            def eliminar_seleccionadas_admin(ev):
                ids_sel = [k for k, c in checks_admin_oc.items() if c.value]
                if not ids_sel:
                    notificar("Marque al menos una OC para eliminarla de Supabase.", "#D97706")
                    return
                try:
                    for id_k in ids_sel:
                        try:
                            supabase.table("registro_recepcion").update({"asn_id": None}).eq("asn_id", id_k).execute()
                        except Exception:
                            pass
                        supabase.table("asn_detalle").delete().eq("asn_id", id_k).execute()
                        supabase.table("asn_cabecera").delete().eq("id", id_k).execute()
                    cerrar_dlg_admin()
                    dd_asn.value = None
                    cargar_lista_asns()
                    cargar_historico_recepciones()
                    notificar(f"{len(ids_sel)} OC(s) eliminadas definitivamente de Supabase.", "#047857")
                except Exception as ex_del:
                    notificar(f"Error eliminando OCs: {ex_del}", "#B91C1C")

            dlg_admin_ocs = ft.AlertDialog(
                modal=True,
                bgcolor="#1E293B",
                title=ft.Row(
                    [
                        ft.Icon(ft.Icons.ADMIN_PANEL_SETTINGS_ROUNDED, color="#F87171", size=24),
                        ft.Text("Administrador: Cerrar o Eliminar OCs / POs Activas", size=16, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ],
                    spacing=8,
                ),
                content=ft.Container(
                    width=680,
                    height=360,
                    content=ft.Column(
                        [
                            ft.Text(
                                "Marque las Órdenes de Compra que desea archivar (Cerrar) o borrar permanentemente de Supabase (Eliminar):",
                                size=11,
                                color=TEXT_MUTED,
                            ),
                            ft.Row(
                                [
                                    boton_primario(
                                        "MARCAR TODAS",
                                        ft.Icons.CHECK_BOX_OUTLINED,
                                        lambda ev: (
                                            [setattr(c, "value", True) for c in checks_admin_oc.values()],
                                            page.update(),
                                        ),
                                        "#334155",
                                        height_val=28,
                                    ),
                                    boton_primario(
                                        "DESMARCAR TODAS",
                                        ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED,
                                        lambda ev: (
                                            [setattr(c, "value", False) for c in checks_admin_oc.values()],
                                            page.update(),
                                        ),
                                        "#475569",
                                        height_val=28,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Container(
                                expand=True,
                                bgcolor="#181E20",
                                border_radius=6,
                                border=ft.Border.all(1, BORDER_COLOR),
                                content=ft.Column([tabla_limpieza_admin], scroll=ft.ScrollMode.AUTO),
                            ),
                        ],
                        spacing=8,
                    ),
                ),
                actions=[
                    ft.TextButton("CANCELAR", on_click=lambda e: cerrar_dlg_admin()),
                    boton_primario("CERRAR SELECCIONADAS (ARCHIVAR)", ft.Icons.ARCHIVE_OUTLINED, cerrar_seleccionadas_admin, "#D97706", height_val=34),
                    boton_primario("ELIMINAR DE SUPABASE", ft.Icons.DELETE_FOREVER_ROUNDED, eliminar_seleccionadas_admin, "#B91C1C", height_val=34),
                ],
                actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )

            page.show_dialog(dlg_admin_ocs)
            page.update()

        def cerrar_conciliacion_asn(e=None):
            try:
                ahora_cierre = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                if filas_conciliacion_export or recepciones_asn_actual:
                    exportar_csv_recepcion_netsuite()
                if asn_actual_id:
                    supabase.table("asn_cabecera").update({"estado": "COMPLETADO"}).eq("id", asn_actual_id).execute()
                cargar_lista_asns()
                cargar_historico_recepciones()
                notificar(f"OC cerrada oficialmente ({ahora_cierre}).", "#047857")
                enviar_correo_acta_po()
            except Exception as ex:
                notificar(f"Error al cerrar OC: {ex}", "#B91C1C")

        def guardar_ajuste_linea_asn(e=None):
            sku_objetivo = (txt_nuevo_sku_po.value or _extraer_sku_limpio_dropdown(dd_edit_sku_asn.value) or "").strip().upper()
            if not asn_actual_id or not sku_objetivo or sku_objetivo == "TODOS":
                notificar("Seleccione una OC activa e indique el SKU.", "#D97706")
                return
            try:
                cajas_n = max(1, int(txt_edit_cajas_esp.value.strip() or "1"))
                mult_n = max(1, int(txt_edit_mult_esp.value.strip() or "1"))
                linea_existente = next((l for l in lineas_asn_actual if str(l["sku"]).upper() == sku_objetivo), None)
                datos_linea = {
                    "asn_id": asn_actual_id,
                    "sku": sku_objetivo,
                    "descripcion_proveedor": (txt_edit_desc_po.value or "Artículo OC").strip(),
                    "cajas_esperadas": cajas_n,
                    "multiplo_empaque": mult_n,
                    "unidades_esperadas": max(1, int(txt_edit_unid_esp.value.strip() or str(cajas_n * mult_n))),
                    "lote_sugerido": (txt_edit_lote_sug.value or "S/L").strip().upper(),
                    "vencimiento_sugerido_cl": normalizar_fecha_sql(txt_edit_venc_sug.value),
                }
                if linea_existente:
                    supabase.table("asn_detalle").update(datos_linea).eq("id", linea_existente["id"]).execute()
                    notificar(f"Línea {sku_objetivo} actualizada.", "#047857")
                else:
                    supabase.table("asn_detalle").insert(datos_linea).execute()
                    notificar(f"SKU {sku_objetivo} agregado a la OC.", "#047857")
                auditar_asn_seleccionado()
            except Exception as ex:
                notificar(f"Error guardando línea: {ex}", "#B91C1C")

        def eliminar_linea_po_seleccionada(e=None):
            sku_del = _extraer_sku_limpio_dropdown(dd_edit_sku_asn.value)
            if not asn_actual_id or not sku_del or sku_del == "TODOS":
                return
            try:
                supabase.table("asn_detalle").delete().eq("asn_id", asn_actual_id).eq("sku", sku_del).execute()
                notificar(f"SKU {sku_del} eliminado de la OC.", "#047857")
                auditar_asn_seleccionado()
            except Exception as ex:
                notificar(f"Error eliminando SKU: {ex}", "#B91C1C")

        # =====================================================================
        # MOTOR IA OPTIMIZADO (CON CACHÉ DE MODELO ACTIVO Y CERO REBOTE 404)
        # =====================================================================
        def _obtener_gemini_api_key() -> str:
            k = (
                os.getenv("GEMINI_API_KEY")
                or os.getenv("GOOGLE_API_KEY")
                or globals().get("GEMINI_API_KEY")
                or ""
            ).strip()
            if not k and ai_client is not None:
                k = str(
                    getattr(ai_client, "_api_key", "")
                    or getattr(getattr(ai_client, "_api_client", None), "api_key", "")
                    or ""
                ).strip()
            return k.strip('"').strip("'")

        _cache_modelo_gemini = {"activo": None}

        def _llamar_gemini_rest_sincrono(ruta_archivo: str, prompt: str) -> str:
            import time
            import mimetypes

            api_key = _obtener_gemini_api_key()
            if not api_key:
                raise RuntimeError("No se encontró GEMINI_API_KEY en las variables de entorno (.env o Render).")

            with open(ruta_archivo, "rb") as f_bin:
                b64_doc = base64.b64encode(f_bin.read()).decode("utf-8")

            mime_t, _ = mimetypes.guess_type(ruta_archivo)
            if not mime_t:
                mime_t = "application/pdf" if ruta_archivo.lower().endswith(".pdf") else "image/jpeg"

            modelos_base = [
                "gemini-2.5-flash",
                "gemini-2.0-flash",
                "gemini-flash-latest",
                "gemini-2.5-flash-lite-preview-06-17",
                "gemini-flash-lite-latest",
            ]

            modelos_prioritarios = []
            if _cache_modelo_gemini["activo"]:
                modelos_prioritarios.append(_cache_modelo_gemini["activo"])
            for m_b in modelos_base:
                if m_b not in modelos_prioritarios:
                    modelos_prioritarios.append(m_b)

            payload_json = {
                "contents": [
                    {
                        "parts": [
                            {"inline_data": {"mime_type": mime_t, "data": b64_doc}},
                            {"text": prompt},
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            }

            errores = []
            sesion_http = requests.Session()

            def _intentar_con_lista(lista_modelos: list):
                for mod_name in lista_modelos:
                    url_gen = f"https://generativelanguage.googleapis.com/v1beta/models/{mod_name}:generateContent?key={api_key}"
                    for intento in range(2):
                        try:
                            resp = sesion_http.post(
                                url_gen,
                                headers={"Content-Type": "application/json"},
                                json=payload_json,
                                timeout=75,
                            )
                            if resp.status_code == 200:
                                data_r = resp.json()
                                cands = data_r.get("candidates") or []
                                if cands:
                                    parts = (cands[0].get("content") or {}).get("parts") or []
                                    for p in parts:
                                        if p.get("text"):
                                            _cache_modelo_gemini["activo"] = mod_name
                                            return p["text"]
                            elif resp.status_code in (503, 429) and intento == 0:
                                time.sleep(1.2)
                                continue
                            else:
                                errores.append(f"{mod_name} ({resp.status_code}): {resp.text[:120]}")
                                break
                        except Exception as ex_req:
                            errores.append(f"{mod_name}: {ex_req}")
                            break
                return None

            # 1. Intentar directo con los modelos oficiales en producción
            respuesta_ok = _intentar_con_lista(modelos_prioritarios)
            if respuesta_ok:
                return respuesta_ok

            # 2. Respaldo dinámico: consultar catálogo de modelos disponibles en la cuenta si los principales fallan
            modelos_respaldo = []
            try:
                r_list = sesion_http.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                    timeout=6,
                )
                if r_list.status_code == 200:
                    excluidos = (
                        "tts", "image", "audio", "live", "embedding",
                        "vision", "robotics", "computer", "aqa", "imagen",
                    )
                    for m in r_list.json().get("models", []):
                        metodos = m.get("supportedGenerationMethods") or []
                        nombre_m = str(m.get("name") or "").replace("models/", "")
                        if "generateContent" in metodos and "gemini" in nombre_m:
                            if not any(x in nombre_m.lower() for x in excluidos) and nombre_m not in modelos_prioritarios:
                                modelos_respaldo.append(nombre_m)
            except Exception:
                pass

            if modelos_respaldo:
                respuesta_ok = _intentar_con_lista(modelos_respaldo)
                if respuesta_ok:
                    return respuesta_ok

            raise RuntimeError(" | ".join(errores[:3]) if errores else "Sin respuesta de Gemini API.")

        def _extraer_json_limpio_ia(texto_resp: str):
            s = (texto_resp or "").strip()
            s = s.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                return json.loads(s)
            except Exception:
                m = re.search(r"(\{.*\}|\[.*\])", s, re.DOTALL)
                if m:
                    return json.loads(m.group(1))
                raise

        modo_carga_ia_actual = {"tipo": "PACKING", "ultimo_nombre": ""}

        async def procesar_packing_ia_desde_ruta(ruta_pdf: str):
            if not ruta_pdf or not os.path.exists(ruta_pdf):
                notificar("No se encontró el archivo PDF subido en el servidor.", "#B91C1C")
                return

            nombre_archivo = os.path.basename(ruta_pdf)
            txt_estado_ia.value = f"Analizando '{nombre_archivo}' (Packing / CAN CODE LIST) con Gemini IA..."
            self.page.update()

            try:
                skus_contexto = ""
                if lineas_asn_actual:
                    lista_ctx = [f"{l.get('sku')} ({l.get('descripcion_proveedor', '')[:30]})" for l in lineas_asn_actual]
                    skus_contexto = (
                        "La Orden de Compra activa tiene estos SKUs registrados: "
                        + ", ".join(lista_ctx)
                        + ". Usa exactamente estos códigos SKU cuando coincidan con el código o descripción del documento. "
                    )

                prompt = (
                    "Actúa como un especialista en comercio exterior y WMS. "
                    "Extrae los datos del Packing List, CAN CODE LIST o Certificado CoA adjunto y devuelve ÚNICAMENTE un JSON válido. "
                    + skus_contexto
                    + "REGLAS IMPORTANTES: "
                    "1. Si el documento NO trae un código de lote alfanumérico explícito (ej. solo trae fechas de expiración), pon 'S/L' en 'lote_sugerido' y pon las fechas únicamente en 'vencimiento_sugerido_cl' en formato DD-MM-YYYY. NUNCA pongas una fecha dentro de 'lote_sugerido'. "
                    "2. Si un mismo SKU tiene múltiples filas con distintos lotes o fechas de vencimiento, suma sus cajas/unidades y une todos sus lotes y fechas separados por coma en la misma línea. "
                    'Formato estricto: {"proveedor": "Nombre proveedor", "orden": "Numero orden", "contenedor_referencia": "Codigo", "fecha_documento": "DD-MM-YYYY", "pallets_esperados": 1, "lineas": [{"sku": "USA603", "descripcion": "Nombre", "cajas_esperadas": 10, "multiplo_empaque": 48, "unidades_esperadas": 480, "lote_sugerido": "S/L", "vencimiento_sugerido_cl": "DD-MM-YYYY"}]}'
                )

                texto_ia = await asyncio.to_thread(_llamar_gemini_rest_sincrono, ruta_pdf, prompt)
                datos_brutos = _extraer_json_limpio_ia(texto_ia)
                datos = datos_brutos[0] if isinstance(datos_brutos, list) and datos_brutos else (datos_brutos if isinstance(datos_brutos, dict) else {})

                reg_es_fecha = re.compile(r"^\d{1,4}[\-\/\.]\d{1,2}[\-\/\.]\d{1,4}$")

                mapa_skus = {}
                for l in datos.get("lineas", []):
                    sku_limpio = str(l.get("sku", "")).strip().upper()
                    if not sku_limpio:
                        continue

                    cajas = max(0, int(float(l.get("cajas_esperadas") or 0)))
                    unid = max(cajas, int(float(l.get("unidades_esperadas") or cajas)))
                    mult = max(1, int(float(l.get("multiplo_empaque") or (unid // cajas if cajas > 0 else 1))))
                    lote_sug = str(l.get("lote_sugerido") or "S/L").strip().upper()
                    venc_sug = str(l.get("vencimiento_sugerido_cl") or "").strip()

                    if sku_limpio not in mapa_skus:
                        mapa_skus[sku_limpio] = {
                            "descripcion": l.get("descripcion", ""),
                            "cajas": 0,
                            "unidades": 0,
                            "multiplo": mult,
                            "lotes": set(),
                            "vencimientos": set(),
                        }

                    mapa_skus[sku_limpio]["cajas"] += cajas
                    mapa_skus[sku_limpio]["unidades"] += unid

                    for lt in lote_sug.split(","):
                        lt_limpio = lt.strip()
                        if not lt_limpio or lt_limpio in ("S/L", "NONE", "NULL"):
                            continue
                        if reg_es_fecha.match(lt_limpio):
                            f_norm = normalizar_fecha_sql(lt_limpio)
                            if f_norm:
                                mapa_skus[sku_limpio]["vencimientos"].add(f_norm)
                        else:
                            mapa_skus[sku_limpio]["lotes"].add(lt_limpio)

                    for v in venc_sug.split(","):
                        v_norm = normalizar_fecha_sql(v.strip())
                        if v_norm and v_norm.upper() not in ("NONE", "NULL", "S/F", ""):
                            mapa_skus[sku_limpio]["vencimientos"].add(v_norm)

                if asn_actual_id is not None and dd_asn.value != "LIBRES":
                    mapa_sku_real_oc = {
                        str(lin.get("sku") or "").strip().upper().replace("-", "").replace(" ", ""): str(lin.get("sku") or "").strip()
                        for lin in lineas_asn_actual
                    }

                    skus_actualizados = 0
                    for sku_ia, info in mapa_skus.items():
                        clave_norm = sku_ia.replace("-", "").replace(" ", "")
                        sku_target = mapa_sku_real_oc.get(clave_norm, sku_ia)

                        lotes_finales = ", ".join(sorted(info["lotes"])) if info["lotes"] else "S/L"
                        venc_finales = ", ".join(sorted(info["vencimientos"])) if info["vencimientos"] else None

                        payload_upd = {
                            "lote_sugerido": lotes_finales,
                            "vencimiento_sugerido_cl": venc_finales,
                        }
                        if info["cajas"] > 0:
                            payload_upd["cajas_esperadas"] = info["cajas"]

                        res_upd = (
                            supabase.table("asn_detalle")
                            .update(payload_upd)
                            .eq("asn_id", asn_actual_id)
                            .eq("sku", sku_target)
                            .execute()
                        )
                        if res_upd.data:
                            skus_actualizados += 1

                    upd_cab = {"archivo_origen": f"OC_NETSUITE + {nombre_archivo}"}
                    if datos.get("contenedor_referencia") and str(datos.get("contenedor_referencia")).upper() not in ("NONE", "NULL", "CODIGO", ""):
                        upd_cab["contenedor_referencia"] = str(datos.get("contenedor_referencia")).strip().upper()
                    try:
                        supabase.table("asn_cabecera").update(upd_cab).eq("id", asn_actual_id).execute()
                    except Exception:
                        pass

                    txt_estado_ia.value = f"Documento procesado ({_cache_modelo_gemini['activo']}): {skus_actualizados} SKUs enriquecidos."
                    notificar(f"¡Éxito! {skus_actualizados} SKUs actualizados en la OC.", "#047857")
                else:
                    orden_str = str(datos.get("orden") or datetime.now().strftime("%H%M%S")).strip()
                    bodega_usr = obtener_bodega_actual()
                    cab = {
                        "codigo_asn": f"OC-{orden_str}",
                        "proveedor": datos.get("proveedor", "PROVEEDOR"),
                        "numero_oc": orden_str,
                        "contenedor_referencia": str(datos.get("contenedor_referencia") or (txt_contenedor.value or "")).strip().upper(),
                        "estado": "EN_RECEPCION",
                        "bodega": bodega_usr,
                    }
                    try:
                        res_cab = supabase.table("asn_cabecera").upsert(cab, on_conflict="codigo_asn").execute()
                    except Exception:
                        cab.pop("bodega", None)
                        res_cab = supabase.table("asn_cabecera").upsert(cab, on_conflict="codigo_asn").execute()
                    nuevo_id = res_cab.data[0]["id"]
                    supabase.table("asn_detalle").delete().eq("asn_id", nuevo_id).execute()

                    detalles = []
                    for sku, info in mapa_skus.items():
                        lotes_finales = ", ".join(sorted(info["lotes"])) if info["lotes"] else "S/L"
                        venc_finales = ", ".join(sorted(info["vencimientos"])) if info["vencimientos"] else None
                        detalles.append(
                            {
                                "asn_id": nuevo_id,
                                "sku": sku,
                                "descripcion_proveedor": info["descripcion"],
                                "multiplo_empaque": info["multiplo"],
                                "cajas_esperadas": max(1, info["cajas"]),
                                "unidades_esperadas": max(1, info["unidades"]),
                                "lote_sugerido": lotes_finales,
                                "vencimiento_sugerido_cl": venc_finales,
                            }
                        )

                    if detalles:
                        supabase.table("asn_detalle").insert(detalles).execute()

                    txt_estado_ia.value = f"OC creada desde PDF ({_cache_modelo_gemini['activo']}): {len(detalles)} SKUs habilitados."
                    notificar(f"OC creada desde PDF con {len(detalles)} SKUs.", "#047857")
                    dd_asn.value = str(nuevo_id)

                cargar_lista_asns()
                auditar_asn_seleccionado()
            except Exception as ex:
                txt_estado_ia.value = f"Error procesando PDF: {ex}"
                notificar(f"Error procesando PDF: {ex}", "#B91C1C")
            finally:
                self.page.update()

        async def procesar_coa_ia_desde_ruta(ruta_pdf: str):
            await procesar_packing_ia_desde_ruta(ruta_pdf)

        async def despachar_archivo_ia_listo(ruta_local: str):
            if modo_carga_ia_actual.get("tipo") == "COA":
                await procesar_coa_ia_desde_ruta(ruta_local)
            else:
                await procesar_packing_ia_desde_ruta(ruta_local)

        def on_upload_ia_event(e):
            err_up = getattr(e, "error", None)
            if err_up:
                txt_estado_ia.value = f"Error al subir PDF: {err_up}"
                self.page.update()
                return
            prog = getattr(e, "progress", None)
            if prog is not None and prog < 1.0:
                txt_estado_ia.value = f"Subiendo archivo al servidor ({int(prog * 100)}%)..."
                self.page.update()
                return

            nombre_f = getattr(e, "file_name", None) or modo_carga_ia_actual.get("ultimo_nombre", "")
            ruta_subida = os.path.join("assets", "uploads", os.path.basename(nombre_f))
            if os.path.exists(ruta_subida):
                self.page.run_task(despachar_archivo_ia_listo, ruta_subida)

        async def manejar_archivos_seleccionados_ia(archivos_lista):
            if not archivos_lista:
                txt_estado_ia.value = "Selección de archivo cancelada."
                self.page.update()
                return

            f_obj = archivos_lista[0]
            nombre_limpio = os.path.basename(getattr(f_obj, "name", "documento.pdf"))
            modo_carga_ia_actual["ultimo_nombre"] = nombre_limpio
            os.makedirs(os.path.join("assets", "uploads"), exist_ok=True)
            ruta_destino = os.path.join("assets", "uploads", nombre_limpio)

            datos_bytes = getattr(f_obj, "bytes", None)
            if datos_bytes:
                with open(ruta_destino, "wb") as f_out:
                    f_out.write(bytes(datos_bytes))
                await despachar_archivo_ia_listo(ruta_destino)
                return

            ruta_local_pc = getattr(f_obj, "path", None)
            if ruta_local_pc and os.path.exists(ruta_local_pc):
                await despachar_archivo_ia_listo(ruta_local_pc)
                return

            txt_estado_ia.value = f"Subiendo '{nombre_limpio}' a la nube..."
            self.page.update()
            upload_url = self.page.get_upload_url(nombre_limpio, 600)
            sig_up = inspect.signature(ft.FilePickerUploadFile.__init__).parameters
            kwargs_up = {"upload_url": upload_url}
            if "name" in sig_up:
                kwargs_up["name"] = nombre_limpio
            if "id" in sig_up and hasattr(f_obj, "id"):
                kwargs_up["id"] = f_obj.id

            arch_up = ft.FilePickerUploadFile(**kwargs_up)
            res_u = selector_archivos_ia.upload([arch_up])
            if inspect.iscoroutine(res_u):
                await res_u

        def on_result_ia_event(e):
            archivos = getattr(e, "files", None)
            self.page.run_task(manejar_archivos_seleccionados_ia, archivos)

        sig_fp = inspect.signature(ft.FilePicker.__init__).parameters
        kwargs_fp = {}
        if "on_result" in sig_fp:
            kwargs_fp["on_result"] = on_result_ia_event
        if "on_upload" in sig_fp:
            kwargs_fp["on_upload"] = on_upload_ia_event

        selector_archivos_ia = ft.FilePicker(**kwargs_fp)
        try:
            if hasattr(ft, "Service") and isinstance(selector_archivos_ia, ft.Service) and hasattr(self.page, "services"):
                self.page.services.append(selector_archivos_ia)
            else:
                self.page.overlay.append(selector_archivos_ia)
        except Exception:
            try:
                self.page.overlay.append(selector_archivos_ia)
            except Exception:
                pass

        async def abrir_selector_web_ia(tipo_doc: str, extensiones: list):
            modo_carga_ia_actual["tipo"] = tipo_doc
            txt_estado_ia.value = f"Seleccione el archivo ({', '.join(extensiones)}) en su navegador..."
            self.page.update()

            sig_pick = inspect.signature(selector_archivos_ia.pick_files).parameters
            kwargs_pick = {
                "allow_multiple": False,
                "allowed_extensions": extensiones,
            }
            if "with_data" in sig_pick:
                kwargs_pick["with_data"] = True

            res_pick = selector_archivos_ia.pick_files(**kwargs_pick)
            if inspect.iscoroutine(res_pick):
                archivos_devueltos = await res_pick
                if archivos_devueltos is not None:
                    lista_f = getattr(archivos_devueltos, "files", archivos_devueltos)
                    await manejar_archivos_seleccionados_ia(lista_f)

        async def seleccionar_y_procesar_packing_ia(e=None):
            await abrir_selector_web_ia("PACKING", ["pdf"])

        async def anexar_certificado_coa_ia(e=None):
            await abrir_selector_web_ia("COA", ["pdf", "png", "jpg", "jpeg"])

        async def ejecutar_accion_menu_po(e=None):
            accion = dd_accion_po.value
            if not accion:
                return

            if accion == "SINCRONIZAR":
                auditar_asn_seleccionado()
                notificar("Recepción sincronizada.", ACCENT_TEAL)
            elif accion == "DESCARGAR_PO":
                descargar_po_netsuite_inbound()
            elif accion in ("PACKING", "PACKING_IA"):
                await seleccionar_y_procesar_packing_ia()
            elif accion in ("COA", "COA_IA"):
                await anexar_certificado_coa_ia()
            elif accion == "IMPRIMIR_TODOS_LPN":
                imprimir_todos_los_lpns_po_activa()
            elif accion == "ACTA_PDF":
                click_exportar_pdf_recepcion()
            elif accion == "EXCEL":
                click_exportar_excel_recepcion()
            elif accion == "CSV_NETSUITE":
                exportar_csv_recepcion_netsuite()
            elif accion == "CERRAR_PO":
                cerrar_conciliacion_asn()

            dd_accion_po.value = None
            page.update()

        dd_accion_po.on_change = ejecutar_accion_menu_po
        dd_accion_po.on_select = ejecutar_accion_menu_po

        async def loop_auto_sync_inbound():
            while auto_sync_inbound_activo:
                await asyncio.sleep(8)
                if auto_sync_inbound_activo and self.get_indice_activo() == 1:
                    auditar_asn_seleccionado()

        def toggle_auto_sync_inbound(e):
            nonlocal auto_sync_inbound_activo
            auto_sync_inbound_activo = bool(e.control.value)
            if auto_sync_inbound_activo:
                notificar("Auto-Sync en vivo activado (cada 8s).", "#04996F")
                page.run_task(loop_auto_sync_inbound)
            else:
                notificar("Auto-Sync en vivo pausado.", "#475569")

        def cambiar_oc_desde_selector_secundario(e, ctrl_dd):
            val_sel = getattr(e, "data", None) or getattr(ctrl_dd, "value", None)
            if val_sel:
                str_v = str(val_sel)
                for op in (ctrl_dd.options or []):
                    if str(op.key) == str_v or str(op.text) == str_v:
                        str_v = str(op.key)
                        break
                if str_v != str(dd_asn.value):
                    dd_asn.value = str_v
                    auditar_asn_seleccionado()

        # --- 5. VINCULACIÓN DE EVENTOS A CONTROLES ---
        txt_mod_lpn_cajas.on_change = recalcular_mod_lpn_totales
        txt_mod_lpn_mult.on_change = recalcular_mod_lpn_totales
        txt_mod_lpn_sueltas.on_change = recalcular_mod_lpn_totales

        txt_edit_cajas_esp.on_change = recalcular_mod_po_unidades
        txt_edit_mult_esp.on_change = recalcular_mod_po_unidades

        dd_edit_sku_asn.on_select = prellenar_edicion_linea_asn
        dd_edit_sku_asn.on_change = prellenar_edicion_linea_asn

        dd_filtro_sku_mod_lpn.on_select = actualizar_tabla_y_selector_lpns
        dd_filtro_sku_mod_lpn.on_change = actualizar_tabla_y_selector_lpns

        dd_edit_lpn_id.on_select = evento_seleccionar_lpn_dropdown
        dd_edit_lpn_id.on_change = evento_seleccionar_lpn_dropdown

        txt_buscar_lpn_mod.on_change = lambda e: actualizar_tabla_y_selector_lpns(mantener_lpn_actual=True)
        txt_buscar_lpn_mod.on_submit = lambda e: actualizar_tabla_y_selector_lpns(mantener_lpn_actual=True)

        dd_qa_po_base.on_select = lambda e: cambiar_oc_desde_selector_secundario(e, dd_qa_po_base)
        dd_qa_po_base.on_change = lambda e: cambiar_oc_desde_selector_secundario(e, dd_qa_po_base)

        dd_mod_po_base.on_select = lambda e: cambiar_oc_desde_selector_secundario(e, dd_mod_po_base)
        dd_mod_po_base.on_change = lambda e: cambiar_oc_desde_selector_secundario(e, dd_mod_po_base)

        dd_asn.on_select = auditar_asn_seleccionado
        dd_asn.on_change = auditar_asn_seleccionado

        dd_fecha_hist_rec.on_select = cargar_historico_recepciones
        dd_fecha_hist_rec.on_change = cargar_historico_recepciones
        txt_buscar_hist_rec.on_change = cargar_historico_recepciones
        txt_fecha_hist_rec.on_change = cargar_historico_recepciones
        btn_guardar_contenedor.on_click = guardar_contenedor_db
        sw_auto_sync_rf.on_change = toggle_auto_sync_inbound
        txt_po_netsuite.on_submit = descargar_po_netsuite_inbound

        # --- 6. COMPOSICIÓN DE VISTAS (ARMADO FINAL DE LA INTERFAZ) ---
        es_admin_usuario = "ADMIN" in str(getattr(self.page, "rol_actual", "")).upper()

        controles_superiores_po = [
            txt_po_netsuite,
            boton_primario(
                "LLAMAR OC",
                ft.Icons.CLOUD_DOWNLOAD_OUTLINED,
                descargar_po_netsuite_inbound,
                ACCENT_BLUE,
                height_val=34,
            ),
            txt_contenedor,
            btn_guardar_contenedor,
            dd_accion_po,
            ft.IconButton(
                icon=ft.Icons.SYNC_ROUNDED,
                icon_color=ACCENT_CYAN,
                tooltip="Sincronizar recepción en vivo",
                on_click=auditar_asn_seleccionado,
            ),
            boton_primario(
                "CARGAR PACKING PDF",
                ft.Icons.UPLOAD_FILE_ROUNDED,
                seleccionar_y_procesar_packing_ia,
                "#4F46E5",
                height_val=34,
            ),
        ]

        if es_admin_usuario:
            controles_superiores_po.append(
                boton_primario(
                    "ADMIN: LIMPIAR OCs",
                    ft.Icons.DELETE_SWEEP_ROUNDED,
                    abrir_gestor_limpieza_ocs_admin,
                    "#B91C1C",
                    height_val=34,
                )
            )

        barra_titulo_monitor = ft.Container(
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            bgcolor="#222A2C",
            border_radius=8,
            border=ft.Border.all(1, BORDER_COLOR),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.LOCAL_SHIPPING_OUTLINED, color=ACCENT_CYAN, size=22),
                                    ft.Text("KPI RECEPCIÓN & CONCILIACIÓN 3-WAY MATCH", size=15, weight=ft.FontWeight.W_900, color=TEXT_WHITE),
                                    ft.Container(width=10),
                                    txt_estado_ia,
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Row(
                                controles_superiores_po,
                                spacing=8,
                                wrap=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    dd_asn,
                ],
                spacing=8,
            ),
        )

        panel_relojes_izquierdo = tarjeta_dark(
            ft.Column(
                [
                    ft.Text("Tiempo promedio de recepción y descarga en andén", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Row(
                        [
                            crear_caja_digital(lbl_dig_dias, "Días", "#8B5CF6", 92),
                            crear_caja_digital(lbl_dig_horas, "Horas", "#8B5CF6", 92),
                            crear_caja_digital(lbl_dig_min, "Minutos", "#8B5CF6", 92),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_AROUND,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=10),
                    ft.Text("Indicadores físicos de conciliación por partida (OC)", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Row(
                        [
                            crear_caja_digital(lbl_inb_cajas, "Cajas (Fís/OC)", ACCENT_TEAL, 86),
                            crear_caja_digital(lbl_inb_unidades, "Unid. Recibidas", ACCENT_BLUE, 86),
                            crear_caja_digital(lbl_inb_pallets, "LPNs Activos", "#D97706", 78),
                            crear_caja_digital(lbl_inb_avance, "Avance OC", "#10B981", 78),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                spacing=8,
            ),
            width_val=415,
        )

        panel_grafico_derecho = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Volumen y avance físico de recepción por SKU (Unidades)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            ft.Row(
                                [
                                    ft.Container(width=12, height=12, bgcolor=ACCENT_BLUE, border_radius=2),
                                    ft.Text("En Proceso", size=10, color=TEXT_MUTED),
                                    ft.Container(width=12, height=12, bgcolor="#10B981", border_radius=2),
                                    ft.Text("100% Validado", size=10, color=TEXT_MUTED),
                                    ft.Container(width=12, height=12, bgcolor="#EF4444", border_radius=2),
                                    ft.Text("Sobrante / Fuera OC", size=10, color=TEXT_MUTED),
                                ],
                                spacing=6,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=6),
                    ft.Container(
                        height=155,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                        bgcolor="#181E20",
                        border_radius=6,
                        alignment=ft.Alignment.BOTTOM_LEFT,
                        content=fila_barras_po,
                    ),
                ],
                spacing=8,
            ),
            expand_val=True,
        )

        # PANEL 1: Recepción Activa
        subvista_inb_recepcion = ft.Column(
            [
                barra_titulo_monitor,
                ft.Row([panel_relojes_izquierdo, panel_grafico_derecho], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text("Detalle de órdenes y conciliación 3-Way Match por partida (OC vs Recepción RF)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                                    ft.Row(
                                        [
                                            sw_auto_sync_rf,
                                            boton_primario("ACTA PDF", ft.Icons.PICTURE_AS_PDF_OUTLINED, click_exportar_pdf_recepcion, ACCENT_TEAL, height_val=30),
                                            boton_primario("ENVIAR CORREO", ft.Icons.EMAIL_OUTLINED, enviar_correo_acta_po, "#0F766E", height_val=30),
                                            boton_primario("EXCEL", ft.Icons.TABLE_VIEW_OUTLINED, click_exportar_excel_recepcion, "#0284C7", height_val=30),
                                            boton_primario("IMPRIMIR LPNs (15x10)", ft.Icons.PRINT_ROUNDED, imprimir_todos_los_lpns_po_activa, "#4F46E5", height_val=30),
                                        ],
                                        spacing=8,
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                wrap=True,
                            ),
                            ft.Divider(color=BORDER_COLOR, height=1),
                            cont_tabla_inb_cruce,
                            ft.Divider(color=BORDER_COLOR, height=8),
                            ft.Text("Trazabilidad de Pallets (LPNs) escaneados en andén para esta Orden de Compra", size=12, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
                            cont_tabla_inb_lpns,
                        ],
                        spacing=6,
                    )
                ),
            ],
            spacing=10,
        )

        # PANEL 2: Consultor Histórico
        subvista_inb_consultas = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text("2. CONSULTOR HISTÓRICO DE RECEPCIONES POR DÍA Y OC/PO REAL", size=14, weight=ft.FontWeight.W_900, color=TEXT_WHITE),
                                    ft.Text("Filtre por Fecha o haga clic en 'SOLO SIN PO', marque los artículos deseados y descargue sus etiquetas LPN, Acta PDF o Excel.", size=11, color=TEXT_MUTED),
                                ],
                                spacing=2,
                            ),
                            ft.Row(
                                [
                                    dd_fecha_hist_rec,
                                    txt_fecha_hist_rec,
                                    txt_buscar_hist_rec,
                                    boton_primario("SOLO SIN PO", ft.Icons.INVENTORY_2_OUTLINED, filtrar_solo_sin_po_hist, "#D97706"),
                                    boton_primario("FILTRAR", ft.Icons.SEARCH_ROUNDED, cargar_historico_recepciones, ACCENT_TEAL),
                                    boton_primario("LIMPIAR", ft.Icons.FILTER_ALT_OFF_OUTLINED, limpiar_filtros_historico, "#475569"),
                                ],
                                spacing=8,
                                wrap=True,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=4),
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    boton_primario("MARCAR TODOS", ft.Icons.CHECK_BOX_OUTLINED, lambda e: marcar_desmarcar_hist(True), "#334155", height_val=28),
                                    boton_primario("DESMARCAR TODOS", ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED, lambda e: marcar_desmarcar_hist(False), "#475569", height_val=28),
                                ],
                                spacing=6,
                            ),
                            ft.Row(
                                [
                                    boton_primario("IMPRIMIR LPNs MARCADOS (15x10)", ft.Icons.PRINT_ROUNDED, imprimir_lpns_seleccionados_hist, "#4F46E5", height_val=30),
                                    boton_primario("BAJAR ACTA PDF (MARCADOS)", ft.Icons.PICTURE_AS_PDF_OUTLINED, descargar_pdf_historico_filtrado, ACCENT_TEAL, height_val=30),
                                    boton_primario("BAJAR EXCEL (MARCADOS)", ft.Icons.TABLE_VIEW_OUTLINED, exportar_excel_seleccionados_hist, ACCENT_BLUE, height_val=30),
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Text("DESGLOSE RÁPIDO POR DÍA DE RECEPCIÓN Y N° DE OC/PO (CLIC PARA FILTRAR DÍA):", size=10, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
                    fila_resumen_dias_hist,
                    ft.Divider(color=BORDER_COLOR, height=4),
                    cont_tabla_hist_rec,
                ],
                spacing=8,
            )
        )

        # PANEL 3: Aseguramiento de Calidad (QA)
        subvista_inb_qa = tarjeta_dark(
            ft.Column(
                [
                    ft.Text("3. ASEGURAMIENTO DE CALIDAD (QA): BLOQUEO Y LIBERACIÓN DE LOTES", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Divider(color=BORDER_COLOR, height=1),
                    ft.Row(
                        [
                            dd_qa_po_base,
                            dd_qa_lpn,
                            dd_qa_estado,
                            boton_primario("APLICAR A LPN", ft.Icons.VERIFIED_USER_OUTLINED, actualizar_dictamen_qa_lpn, ACCENT_BLUE),
                            boton_primario("LIBERAR TODA LA OC", ft.Icons.DONE_ALL_ROUNDED, aplicar_qa_masivo_toda_la_po, ACCENT_TEAL),
                        ],
                        wrap=True,
                        spacing=8,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=6),
                    cont_tabla_qa_po,
                ],
                spacing=8,
            )
        )

        # PANEL 4: 4.1 Modificación de Líneas OC (Arriba) + 4.2 Modificación de Pallets Físicos con Tabla y Editor Unitario (Abajo)
        subvista_inb_modificacion = ft.Column(
            [
                # 4.1 PRIMERO: MODIFICACIÓN DOCUMENTAL DE LÍNEAS DE LA ORDEN DE COMPRA
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Row(
                                        [
                                            ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, color=ACCENT_CYAN, size=20),
                                            ft.Text("4.1 MODIFICACIÓN DOCUMENTAL DE LÍNEAS DE LA ORDEN DE COMPRA (OC)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                                        ],
                                        spacing=8,
                                    ),
                                    dd_mod_po_base,
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                wrap=True,
                            ),
                            ft.Divider(color=BORDER_COLOR, height=1),
                            ft.Row(
                                [
                                    dd_edit_sku_asn,
                                    txt_nuevo_sku_po,
                                    txt_edit_desc_po,
                                    txt_edit_cajas_esp,
                                    txt_edit_mult_esp,
                                    txt_edit_unid_esp,
                                    txt_edit_lote_sug,
                                    txt_edit_venc_sug,
                                    boton_primario("GUARDAR EN OC", ft.Icons.SAVE_OUTLINED, guardar_ajuste_linea_asn, ACCENT_TEAL),
                                    boton_primario("ELIMINAR LÍNEA", ft.Icons.DELETE_OUTLINE, eliminar_linea_po_seleccionada, "#B91C1C"),
                                ],
                                wrap=True,
                                spacing=8,
                            ),
                        ],
                        spacing=8,
                    )
                ),

                # 4.2 ABAJO: MODIFICACIÓN DE PALLETS FÍSICOS (ELEGIR ENTRE SKU O LPN + EDITOR UNITARIO + TABLA DE LPNs)
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Column(
                                        [
                                            ft.Row(
                                                [
                                                    ft.Icon(ft.Icons.PALLET, color=ACCENT_CYAN, size=20),
                                                    ft.Text("4.2 MODIFICACIÓN DE PALLETS FÍSICOS (LPNs) INGRESADOS", size=13, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
                                                ],
                                                spacing=8,
                                            ),
                                            lbl_resumen_lista_lpns,
                                        ],
                                        spacing=2,
                                    ),
                                    ft.Row(
                                        [
                                            dd_filtro_sku_mod_lpn,
                                            dd_edit_lpn_id,
                                            txt_buscar_lpn_mod,
                                            boton_primario(
                                                "LLAMAR LPNs",
                                                ft.Icons.SEARCH_ROUNDED,
                                                lambda ev: actualizar_tabla_y_selector_lpns(mantener_lpn_actual=False),
                                                ACCENT_BLUE,
                                                height_val=34,
                                            ),
                                            boton_primario(
                                                "VER TODOS",
                                                ft.Icons.LIST_ALT_ROUNDED,
                                                lambda ev: (
                                                    setattr(dd_filtro_sku_mod_lpn, "value", "TODOS"),
                                                    setattr(txt_buscar_lpn_mod, "value", ""),
                                                    actualizar_tabla_y_selector_lpns(mantener_lpn_actual=False),
                                                ),
                                                "#475569",
                                                height_val=34,
                                            ),
                                        ],
                                        spacing=8,
                                        wrap=True,
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                wrap=True,
                            ),
                            ft.Divider(color=BORDER_COLOR, height=4),

                            # BLOQUE DE EDICIÓN DE LPN UNITARIO
                            ft.Container(
                                padding=12,
                                bgcolor="#181E20",
                                border_radius=8,
                                border=ft.Border.all(1.2, ACCENT_CYAN),
                                content=ft.Column(
                                    [
                                        lbl_lpn_unitario_activo,
                                        ft.Row(
                                            [
                                                txt_mod_lpn_cod,
                                                txt_mod_lpn_sku,
                                                txt_mod_lpn_cajas,
                                                txt_mod_lpn_mult,
                                                txt_mod_lpn_sueltas,
                                                txt_mod_lpn_totales,
                                                txt_mod_lpn_lote,
                                                txt_mod_lpn_venc,
                                                dd_mod_lpn_qa,
                                                boton_primario(
                                                    "GUARDAR CAMBIOS EN LPN",
                                                    ft.Icons.SAVE_AS_OUTLINED,
                                                    guardar_modificacion_lpn_fisico,
                                                    "#047857",
                                                    height_val=34,
                                                ),
                                                boton_primario(
                                                    "IMPRIMIR 15x10",
                                                    ft.Icons.PRINT_OUTLINED,
                                                    lambda ev: reimprimir_desde_fila((txt_mod_lpn_cod.value or "").strip()),
                                                    ACCENT_TEAL,
                                                    height_val=34,
                                                ),
                                                boton_primario(
                                                    "ELIMINAR LPN",
                                                    ft.Icons.DELETE_FOREVER_OUTLINED,
                                                    eliminar_lpn_fisico,
                                                    "#B91C1C",
                                                    height_val=34,
                                                ),
                                            ],
                                            wrap=True,
                                            spacing=8,
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                            ),

                            ft.Text(
                                "TABLA DE PALLETS (LPNs) DEL SKU SELECCIONADO (Haga clic en 'EDITAR' en cualquier fila para cargarla arriba):",
                                size=11,
                                weight=ft.FontWeight.BOLD,
                                color=TEXT_MUTED,
                            ),
                            cont_tabla_mod_lpns,
                        ],
                        spacing=8,
                    )
                ),
            ],
            spacing=10,
        )

        contenedor_subvista_inbound = ft.Container(content=subvista_inb_recepcion)

        col_inbound = ft.Column([contenedor_subvista_inbound], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

        self.vista = ft.Container(padding=14, bgcolor=BG_MODULO, content=col_inbound, expand=True)
        self.contenedor = contenedor_subvista_inbound
        self.sub_recepcion = subvista_inb_recepcion
        self.sub_consultas = subvista_inb_consultas
        self.sub_qa = subvista_inb_qa
        self.sub_modificacion = subvista_inb_modificacion
        self.cargar_lista_asns_func = cargar_lista_asns
        self.cargar_historico_recepciones_func = cargar_historico_recepciones
        self.auditar_asn_seleccionado_func = auditar_asn_seleccionado

    def cargar_lista_asns(self):
        self.cargar_lista_asns_func()

    def sel_sub_inb(self, idx: int):
        self.contenedor.content = [self.sub_recepcion, self.sub_consultas, self.sub_qa, self.sub_modificacion][idx]
        if idx == 1:
            self.cargar_historico_recepciones_func()
        elif idx in (2, 3):
            self.auditar_asn_seleccionado_func()
        self.page.update()

        cargar_datos_vivos_panel_izquierdo()
        page.on_resize = adaptar_resolucion_automatica
        page.controls.clear()
        page.overlay.clear()
        page.bgcolor = COLOR_BG_PORTAL
        page.add(ft.Column([encabezado, cuerpo_principal], spacing=0, expand=True))
        adaptar_resolucion_automatica()
        threading.Thread(target=loop_mascota_background, daemon=True).start()


if __name__ == "__main__":
    try:
        os.makedirs(os.path.join("assets", "uploads"), exist_ok=True)
        os.makedirs(os.path.join("assets", "descargas"), exist_ok=True)
        if not os.environ.get("FLET_SECRET_KEY"):
            os.environ["FLET_SECRET_KEY"] = os.environ.get("WMS_PASSWORD_SALT", "ludipek_secret_upload_key_2026")

        puerto_cloud = int(os.environ.get("PORT", 8557))
        print(f"[BOOT] Iniciando servidor LUDIPEK WMS en 0.0.0.0:{puerto_cloud}...", flush=True)

        ft.run(
            main,
            view=ft.AppView.WEB_BROWSER,
            port=puerto_cloud,
            host="0.0.0.0",
            assets_dir="assets",
            upload_dir=os.path.join("assets", "uploads"),
        )
    except Exception as ex_boot:
        print(f"[FATAL] Error al iniciar main.py: {ex_boot}", flush=True)
        traceback.print_exc()
        raise