import os
import json
import inspect
import asyncio
from datetime import datetime
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

        def notificar(texto: str, color: str = "#0284C7"):
            from dependencias import notificar_global
            notificar_global(self.page, texto, color)

        def reimprimir_desde_fila(lpn_cod: str):
            from dependencias import reimprimir_desde_fila_global
            reimprimir_desde_fila_global(self.page, lpn_cod)

        def mostrar_aviso_ingreso_modal(lpn_str, sku_str, unid_str, lote_str, qa_str):
            from dependencias import mostrar_aviso_ingreso_modal_global
            mostrar_aviso_ingreso_modal_global(self.page, lpn_str, sku_str, unid_str, lote_str, qa_str)

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
                content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
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
                content_padding=ft.Padding.symmetric(horizontal=12, vertical=8),
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

        # --- 3. DEFINICIÓN DE TODOS LOS CONTROLES VISUALES BASE ---
        dd_asn = dropdown_dark(label="Orden de Compra Activa (PO)", expand=True)
        txt_po_netsuite = texto_dark(label="N° PO", width=120)
        txt_contenedor = texto_dark(label="Contenedor / Guía", width=150)
        txt_ns_location_id = texto_dark(label="Location ID NS", value="1", width=105, keyboard_type=ft.KeyboardType.NUMBER)
        btn_guardar_contenedor = ft.IconButton(
            icon=ft.Icons.SAVE_OUTLINED,
            icon_color=ACCENT_CYAN,
            tooltip="Guardar N° Contenedor",
        )

        dd_accion_po = dropdown_dark(
            label="Operaciones de Recepción (PO) - Clic para ejecutar",
            width=310,
            value=None,
            options=[
                opt_w("SINCRONIZAR", "1. Sincronizar Recepción de Andén (RF)"),
                opt_w("DESCARGAR_PO", "2. Descargar PO desde NetSuite (ERP)"),
                opt_w("PACKING", "3. Cargar Packing List PDF"),
                opt_w("COA", "4. Anexar Certificado CoA PDF"),
                opt_w("IMPRIMIR_TODOS_LPN", "5. Imprimir TODOS los LPNs de la PO (15x10)"),
                opt_w("ACTA_PDF", "6. Exportar Acta Oficial de PO (PDF)"),
                opt_w("EXCEL", "7. Exportar Conciliación a Excel (.XLSX)"),
                opt_w("CSV_NETSUITE", "8. Generar CSV Item Receipt (NetSuite)"),
                opt_w("CERRAR_PO", "9. Cerrar PO + Emitir CSV NetSuite"),
            ],
        )

        txt_estado_ia = ft.Text(
            "Monitor en línea. Seleccione una PO o ejecute una acción.",
            size=11,
            color=ACCENT_CYAN,
        )
        txt_buscar_hist_rec = texto_dark(
            label="Buscar por N° PO Real, Proveedor, LPN, SKU o Lote...",
            width=290,
        )
        dd_fecha_hist_rec = dropdown_dark(
            label="📅 Día de Recepción",
            width=255,
            value="TODAS",
            options=[opt_w("TODAS", "TODAS LAS FECHAS (POR DÍA)")],
        )
        txt_fecha_hist_rec = texto_dark(
            label="Día exacto (DD-MM-YYYY)",
            width=165,
        )
        fila_resumen_dias_hist = ft.Row(spacing=8, wrap=True)
        dd_mod_po_base = dropdown_dark(label="Orden de Compra (PO) Activa a Modificar", width=360)

        lbl_dig_dias = ft.Text("00", size=26, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_dig_horas = ft.Text("00", size=26, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_dig_min = ft.Text("00", size=26, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_inb_cajas = ft.Text("0/0", size=17, weight=ft.FontWeight.W_900, color="#34D399", font_family="Consolas")
        lbl_inb_unidades = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color=TEXT_WHITE, font_family="Consolas")
        lbl_inb_pallets = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color="#FBBF24", font_family="Consolas")
        lbl_inb_avance = ft.Text("0%", size=18, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")

        fila_barras_po = ft.Row(
            spacing=18,
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.END,
            scroll=ft.ScrollMode.AUTO,
        )

        dd_qa_po_base = dropdown_dark(label="1. Orden de Compra (PO) Base para QA", width=330)
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

        dd_edit_sku_asn = dropdown_dark(label="Seleccionar SKU de la PO", width=210)
        txt_nuevo_sku_po = texto_dark(label="O escribir SKU (Nuevo/Editar)", width=155)
        txt_edit_desc_po = texto_dark(label="Descripción Producto", width=210)
        txt_edit_cajas_esp = texto_dark(label="Cajas PO", width=90, keyboard_type=ft.KeyboardType.NUMBER)
        txt_edit_mult_esp = texto_dark(label="Múltiplo", width=85, keyboard_type=ft.KeyboardType.NUMBER)
        txt_edit_unid_esp = texto_dark(label="Unidades PO", width=105, keyboard_type=ft.KeyboardType.NUMBER)
        txt_edit_lote_sug = texto_dark(label="Lote Oficial", width=130)
        txt_edit_venc_sug = texto_dark(label="Vencimiento (YYYY-MM-DD)", width=155)

        dd_edit_lpn_id = dropdown_dark(label="Seleccionar Registro LPN a Modificar", width=300)
        txt_mod_lpn_cod = texto_dark(label="Código LPN", width=155)
        txt_mod_lpn_sku = texto_dark(label="SKU", width=135)
        txt_mod_lpn_cajas = texto_dark(label="Cajas", width=85, keyboard_type=ft.KeyboardType.NUMBER)
        txt_mod_lpn_mult = texto_dark(label="Múltiplo", width=85, keyboard_type=ft.KeyboardType.NUMBER)
        txt_mod_lpn_sueltas = texto_dark(label="Sueltas", width=85, keyboard_type=ft.KeyboardType.NUMBER)
        txt_mod_lpn_totales = texto_dark(label="Unid. Totales", width=105, keyboard_type=ft.KeyboardType.NUMBER)
        txt_mod_lpn_lote = texto_dark(label="Lote Físico", width=130)
        txt_mod_lpn_venc = texto_dark(label="Vencimiento (YYYY-MM-DD)", width=155)
        dd_mod_lpn_qa = dropdown_dark(
            label="Estado QA",
            width=165,
            value="APROBADO",
            options=[
                opt_w("APROBADO", "APROBADO"),
                opt_w("CUARENTENA", "CUARENTENA"),
                opt_w("RECHAZADO", "RECHAZADO"),
            ],
        )

        sw_auto_sync_rf = ft.Switch(
            label="Auto-Sync RF",
            value=False,
            active_color="#10B981",
        )

        # TABLAS
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
                ft.DataColumn(ft.Text("EMPAQUE PO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("UNID. PO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
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
            column_spacing=14,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("FECHA RECEPCIÓN", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                ft.DataColumn(ft.Text("N° PO", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
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
            if not texto:
                return None
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(texto, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            return texto

        def recalcular_mod_lpn_totales(e=None):
            try:
                c = max(0, int(txt_mod_lpn_cajas.value.strip() or "0"))
                m = max(1, int(txt_mod_lpn_mult.value.strip() or "1"))
                s = max(0, int(txt_mod_lpn_sueltas.value.strip() or "0"))
                txt_mod_lpn_totales.value = str((c * m) + s)
                page.update()
            except Exception:
                pass

        def recalcular_mod_po_unidades(e=None):
            try:
                c = max(1, int(txt_edit_cajas_esp.value.strip() or "1"))
                m = max(1, int(txt_edit_mult_esp.value.strip() or "1"))
                txt_edit_unid_esp.value = str(c * m)
                page.update()
            except Exception:
                pass

        def prellenar_edicion_linea_asn(e=None):
            sku_sel = dd_edit_sku_asn.value
            linea = next((l for l in lineas_asn_actual if l["sku"] == sku_sel), None)
            if linea:
                txt_nuevo_sku_po.value = str(linea.get("sku") or "")
                txt_edit_desc_po.value = str(linea.get("descripcion_proveedor") or "")
                txt_edit_cajas_esp.value = str(linea.get("cajas_esperadas") or 1)
                txt_edit_mult_esp.value = str(linea.get("multiplo_empaque") or 1)
                txt_edit_unid_esp.value = str(linea.get("unidades_esperadas") or 1)
                txt_edit_lote_sug.value = str(linea.get("lote_sugerido") or "S/L")
                txt_edit_venc_sug.value = str(linea.get("vencimiento_sugerido_cl") or "")
                page.update()

        def prellenar_edicion_lpn_fisico(e=None):
            id_sel = dd_edit_lpn_id.value
            if not id_sel:
                return
            reg = next((r for r in recepciones_asn_actual if str(r.get("id")) == str(id_sel)), None)
            if reg:
                lote_limpio, qa_actual = extraer_estado_qa(reg.get("lote", "S/L"))
                txt_mod_lpn_cod.value = str(reg.get("lpn") or "")
                txt_mod_lpn_sku.value = str(reg.get("sku") or "")
                txt_mod_lpn_cajas.value = str(reg.get("cajas") or 0)
                txt_mod_lpn_mult.value = str(reg.get("multiplo_aplicado") or 1)
                txt_mod_lpn_sueltas.value = str(reg.get("unidades_sueltas") or 0)
                txt_mod_lpn_totales.value = str(reg.get("unidades_totales") or 0)
                txt_mod_lpn_lote.value = lote_limpio
                txt_mod_lpn_venc.value = str(reg.get("fecha_vencimiento_cl") or "")
                dd_mod_lpn_qa.value = qa_actual
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

        def construir_columna_grafico(sku_lbl: str, unid_rec: int, unid_esp: int, max_escala: int):
            altura_max_px = 105
            ratio = min(1.0, unid_rec / max(1, max_escala))
            alto_barra = max(14, int(ratio * altura_max_px))
            pct_sku = int(round((unid_rec / max(1, unid_esp)) * 100)) if unid_esp > 0 else 100
            color_b = "#10B981" if pct_sku >= 100 else (ACCENT_BLUE if pct_sku > 0 else "#475569")

            return ft.Column(
                [
                    ft.Text(f"{unid_rec}", size=10, color=TEXT_WHITE, weight=ft.FontWeight.BOLD),
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
                    ft.Text(sku_lbl[:10], size=9, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
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
                notificar("Seleccione un LPN de la PO para aplicar el dictamen de Calidad.", "#D97706")
                return
            cambiar_qa_rapido_lpn(lpn_sel, nuevo_qa)

        def aplicar_qa_masivo_toda_la_po(e=None):
            nuevo_qa = dd_qa_estado.value or "APROBADO"
            if not recepciones_asn_actual:
                notificar("No hay pallets registrados en esta PO.", "#D97706")
                return
            try:
                for fila in recepciones_asn_actual:
                    lote_base, _ = extraer_estado_qa(fila.get("lote", "S/L"))
                    supabase.table("registro_recepcion").update({"lote": formatear_lote_con_qa(lote_base, nuevo_qa)}).eq("id", fila["id"]).execute()
                notificar(f"Dictamen QA masivo [{nuevo_qa}] aplicado a los {len(recepciones_asn_actual)} registros de la PO.", "#047857")
                auditar_asn_seleccionado()
            except Exception as ex:
                notificar(f"Error en liberación masiva QA: {ex}", "#B91C1C")

        def auditar_asn_seleccionado(e=None):
            nonlocal asn_actual_id, cabecera_asn_actual, lineas_asn_actual, recepciones_asn_actual, filas_conciliacion_export
            if not dd_asn.value:
                return
            dd_qa_po_base.value = dd_asn.value

            try:
                res_maestra = supabase.table("maestra_sku").select("sku, descripcion").execute()
                mapa_nombres_maestra = {str(r["sku"]).strip().upper(): str(r.get("descripcion", "")) for r in res_maestra.data}

                if dd_asn.value == "LIBRES":
                    asn_actual_id = None
                    cabecera_asn_actual = {
                        "codigo_asn": "PO-LIBRE",
                        "proveedor": "RECEPCION DIRECTA SIN PO",
                        "numero_oc": "S/OC",
                        "estado": "ACTIVO",
                        "contenedor_referencia": "",
                    }
                    lineas_asn_actual = []
                    recepciones_asn_actual = (
                        supabase.table("registro_recepcion")
                        .select("*")
                        .is_("asn_id", "null")
                        .order("id", desc=True)
                        .limit(100)
                        .execute()
                        .data
                    )
                else:
                    asn_actual_id = int(dd_asn.value)
                    res_cab = supabase.table("asn_cabecera").select("*").eq("id", asn_actual_id).execute()
                    cabecera_asn_actual = res_cab.data[0] if res_cab.data else {}
                    lineas_asn_actual = supabase.table("asn_detalle").select("*").eq("asn_id", asn_actual_id).order("sku").execute().data
                    recepciones_asn_actual = supabase.table("registro_recepcion").select("*").eq("asn_id", asn_actual_id).order("id", desc=True).execute().data

                actualizar_reloj_descarga(recepciones_asn_actual)
                txt_contenedor.value = str(cabecera_asn_actual.get("contenedor_referencia") or "")

                dd_edit_sku_asn.options = [opt_w(l["sku"], f"{l['sku']} - {str(l.get('descripcion_proveedor',''))[:30]}") for l in lineas_asn_actual]
                if lineas_asn_actual and not dd_edit_sku_asn.value:
                    dd_edit_sku_asn.value = lineas_asn_actual[0]["sku"]
                    prellenar_edicion_linea_asn()

                lpns_lista = sorted({str(r.get("lpn")) for r in recepciones_asn_actual if r.get("lpn")})
                dd_qa_lpn.options = [opt_w(c, c) for c in lpns_lista]
                if lpns_lista and (not dd_qa_lpn.value or dd_qa_lpn.value not in lpns_lista):
                    dd_qa_lpn.value = lpns_lista[0]

                dd_edit_lpn_id.options = [
                    opt_w(str(r["id"]), f"#{r['id']} | {r.get('lpn')} | SKU: {r.get('sku')} | {r.get('unidades_totales', 0)} UN")
                    for r in recepciones_asn_actual
                ]
                if recepciones_asn_actual and not dd_edit_lpn_id.value:
                    dd_edit_lpn_id.value = str(recepciones_asn_actual[0]["id"])
                    prellenar_edicion_lpn_fisico()

                mapa_rec_sku = {}
                for r in recepciones_asn_actual:
                    s = str(r.get("sku", "")).strip()
                    lote_c, _ = extraer_estado_qa(r.get("lote", "S/L"))
                    if s not in mapa_rec_sku:
                        mapa_rec_sku[s] = {"cajas": 0, "unidades": 0, "multiplo": int(r.get("multiplo_aplicado") or 1), "lotes": set(), "vencimientos": set()}
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
                fuente_lineas = (
                    lineas_asn_actual
                    if lineas_asn_actual
                    else [
                        {
                            "id": None,
                            "sku": k,
                            "descripcion_proveedor": mapa_nombres_maestra.get(k.upper(), "Ingreso Directo"),
                            "cajas_esperadas": v["cajas"],
                            "multiplo_empaque": v["multiplo"],
                            "unidades_esperadas": v["unidades"],
                            "lote_sugerido": "S/L",
                            "vencimiento_sugerido_cl": "S/F",
                        }
                        for k, v in mapa_rec_sku.items()
                    ]
                )
                max_unid_grafico = max([int(l.get("unidades_esperadas") or 1) for l in fuente_lineas] + [v["unidades"] for v in mapa_rec_sku.values()] + [1])

                for l in fuente_lineas:
                    sku_code = str(l["sku"]).strip()
                    desc_completa = mapa_nombres_maestra.get(sku_code.upper()) or str(l.get("descripcion_proveedor") or "-")
                    cajas_esp = int(l.get("cajas_esperadas") or 0)
                    mult_emp = int(l.get("multiplo_empaque") or 1)
                    unid_esp = int(l.get("unidades_esperadas") or (cajas_esp * mult_emp))

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
                    if dif_unid == 0 and unid_esp > 0:
                        txt_dif, color_dif, estado_txt = "0 (OK)", "#34D399", "VALIDADA"
                        badge_linea = crear_badge_estado("VALIDADA", "#065F46", "#D1FAE5")
                    elif unid_rec == 0:
                        txt_dif, color_dif, estado_txt = f"-{unid_esp} UN", TEXT_MUTED, "PENDIENTE"
                        badge_linea = crear_badge_estado("PENDIENTE", "#CBD5E1", "#334155")
                    elif dif_unid < 0:
                        txt_dif, color_dif, estado_txt = f"{dif_unid} UN", "#FBBF24", "PARCIAL"
                        badge_linea = crear_badge_estado("PARCIAL", "#92400E", "#FEF3C7")
                    else:
                        txt_dif, color_dif, estado_txt = f"+{dif_unid} UN", "#F87171", "SOBRANTE"
                        badge_linea = crear_badge_estado("SOBRANTE", "#991B1B", "#FEE2E2")

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
                            "lotes_reales": f"{lotes_reales} ({venc_reales})",
                            "estado": estado_txt,
                        }
                    )
                    fila_barras_po.controls.append(construir_columna_grafico(sku_code, unid_rec, unid_esp, max_unid_grafico))

                    tabla_cruce_inbound.rows.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(sku_code, weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(desc_completa[:28], size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"{cajas_esp} Cj x {mult_emp}", size=11, color=TEXT_MUTED)),
                                ft.DataCell(ft.Text(f"{unid_esp} UN", size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"{str(l.get('lote_sugerido') or 'S/L')} | {str(l.get('vencimiento_sugerido_cl') or 'S/F')}", size=11, color=TEXT_MUTED)),
                                ft.DataCell(ft.Text(f"{cajas_rec} Cj", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"{unid_rec} UN", weight=ft.FontWeight.BOLD, color=ACCENT_CYAN, size=11)),
                                ft.DataCell(ft.Text(f"{lotes_reales} | {venc_reales}", size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(txt_dif, weight=ft.FontWeight.BOLD, color=color_dif, size=11)),
                                ft.DataCell(badge_linea),
                            ]
                        )
                    )

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
                notificar(f"Error auditando PO: {ex}", "#B91C1C")

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
                notificar("Seleccione una PO activa primero.", "#D97706")

        def cargar_lista_asns(e=None):
            try:
                res = supabase.table("asn_cabecera").select("*").neq("estado", "COMPLETADO").order("id", desc=True).execute()
                opciones = [opt_w("LIBRES", "RECEPCIONES DIRECTAS SIN PO (INGRESOS LIBRES)")]
                for r in res.data:
                    nombre_po = obtener_nombre_po_cabecera(r)
                    opciones.append(opt_w(str(r["id"]), f"PO {nombre_po} | {r.get('proveedor','')} | {r.get('estado','ACTIVO')}"))
                dd_asn.options = opciones
                dd_qa_po_base.options = list(opciones)
                dd_mod_po_base.options = list(opciones)
                if not dd_asn.value:
                    dd_asn.value = str(res.data[0]["id"]) if res.data else "LIBRES"
                dd_qa_po_base.value = dd_asn.value
                dd_mod_po_base.value = dd_asn.value
                auditar_asn_seleccionado()
                page.update()
            except Exception as ex:
                notificar(f"Error al cargar POs: {ex}", "#B91C1C")

        def extraer_dia_y_hora_recepcion(fila_rec: dict) -> tuple:
            """Devuelve (fecha_iso_yyyy_mm_dd, fecha_cl_dd_mm_yyyy, hora_hh_mm) de la recepción física del LPN."""
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

        def cargar_historico_recepciones(e=None):
            filtro_h = (txt_buscar_hist_rec.value or "").strip().upper()
            filtro_fecha_txt = (txt_fecha_hist_rec.value or "").strip()
            dia_dropdown = dd_fecha_hist_rec.value or "TODAS"

            # Si el usuario escribió una fecha manual (DD-MM-YYYY o YYYY-MM-DD), normalizarla a YYYY-MM-DD
            fecha_manual_iso = ""
            if filtro_fecha_txt:
                for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
                    try:
                        fecha_manual_iso = datetime.strptime(filtro_fecha_txt, fmt).strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue

            try:
                # 1. Cargar mapa de POs reales desde asn_cabecera (activas y cerradas)
                mapa_po_real = {}
                try:
                    res_cabs = supabase.table("asn_cabecera").select("id, numero_oc, codigo_asn, proveedor, estado, contenedor_referencia").limit(1000).execute()
                    for c in (res_cabs.data or []):
                        cid = str(c.get("id"))
                        num_po_limpio = obtener_nombre_po_cabecera(c)
                        mapa_po_real[cid] = {
                            "po_display": f"PO {num_po_limpio}" if num_po_limpio != "LIBRE" else "SIN PO",
                            "po_num": num_po_limpio,
                            "proveedor": str(c.get("proveedor") or "SIN PROVEEDOR").strip(),
                            "estado": str(c.get("estado") or "ACTIVO").strip().upper(),
                            "contenedor": str(c.get("contenedor_referencia") or "").strip(),
                        }
                except Exception:
                    pass

                # 2. Cargar recepciones físicas y enriquecer cada una con su Día de Recepción y N° PO Real
                res_h = supabase.table("registro_recepcion").select("*").order("id", desc=True).limit(600).execute()
                registros_enriquecidos = []
                resumen_por_dia = {}      # {dia_iso: {"fecha_cl": ..., "lpns": set(), "unid": 0, "pos": set()}}
                resumen_dia_y_po = {}     # {(dia_iso, po_display): {"fecha_cl": ..., "po": ..., "lpns": set(), "unid": 0}}

                for r in (res_h.data or []):
                    dia_iso, dia_cl, hora_str = extraer_dia_y_hora_recepcion(r)
                    aid_str = str(r.get("asn_id")) if r.get("asn_id") is not None else ""
                    cont_rec = str(r.get("contenedor") or "").strip().upper()

                    if aid_str and aid_str in mapa_po_real:
                        info_po = mapa_po_real[aid_str]
                        po_real_str = info_po["po_display"]
                        prov_str = info_po["proveedor"]
                    elif cont_rec and not cont_rec.startswith("PO-"):
                        po_real_str = "SIN PO (LIBRE)"
                        prov_str = f"CONT: {cont_rec}"
                    else:
                        po_real_str = f"PO {formatear_nombre_po(cont_rec)}" if cont_rec else "SIN PO"
                        prov_str = "RECEPCIÓN DIRECTA"

                    lpn_h = str(r.get("lpn") or "-").strip()
                    sku_h = str(r.get("sku") or "-").strip()
                    unid_h = int(r.get("unidades_totales") or 0)
                    lote_c, qa_c = extraer_estado_qa(r.get("lote", "S/L"))

                    # Acumular para el selector de Día de Recepción
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
                        "lpn": lpn_h,
                        "sku": sku_h,
                        "lote": lote_c,
                        "qa": qa_c,
                    })

                # 3. Poblar Dropdown de Días de Recepción disponibles
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

                # 4. Construir chips rápidos de Recepción por Día y PO (muestra la misma PO separada si se recibió en 2 días)
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

                # 5. Filtrar y ordenar por (dia_iso DESC, po_real ASC, id DESC) para separar visualmente por día
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

                # 6. Llenar tabla insertando una fila separadora cada vez que cambia el Día de Recepción (y PO)
                tabla_historico_recepciones.rows.clear()
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
                                    ft.DataCell(ft.Text("-", size=10, color=TEXT_MUTED)),
                                ],
                            )
                        )

                    lpn_h = item["lpn"]
                    qa_c = item["qa"]
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
            if not recepciones_asn_actual:
                notificar("No hay pallets registrados en esta PO para imprimir.", "#D97706")
                return
            try:
                cod_po = obtener_nombre_po_cabecera(cabecera_asn_actual)
                ruta = generar_pdf_masivo_lpns_po(cod_po, recepciones_asn_actual)
                descargar_o_abrir_archivo(self.page, ruta)
                lpns_cnt = len({r.get("lpn") for r in recepciones_asn_actual if r.get("lpn")})
                notificar(f"PDF generado con las {lpns_cnt} etiquetas LPN de PO {cod_po}: {ruta}", "#047857")
            except Exception as ex:
                notificar(f"Error al imprimir lote de LPNs: {ex}", "#B91C1C")

        def abrir_modal_enviar_correo_acta(cabecera_po: dict, lineas_conciliacion: list, ruta_pdf_generado: str = None):
            oc_num = obtener_nombre_po_cabecera(cabecera_po)
            prov_nom = str(cabecera_po.get("proveedor") or "PROVEEDOR").strip()
            cont_ref = str(cabecera_po.get("contenedor_referencia") or "").strip()
            fecha_hoy = datetime.now().strftime("%d-%m-%Y %H:%M")

            tot_esp = sum(int(x.get("unidades_esperadas") or 0) for x in lineas_conciliacion)
            tot_rec = sum(int(x.get("unidades_recibidas") or 0) for x in lineas_conciliacion)
            dif_tot = tot_rec - tot_esp

            lineas_texto = []
            for l in lineas_conciliacion:
                sku_l = l.get("sku", "-")
                esp_l = int(l.get("unidades_esperadas") or 0)
                rec_l = int(l.get("unidades_recibidas") or 0)
                dif_l = rec_l - esp_l
                est_l = "OK" if dif_l == 0 else (f"SOBRANTE +{dif_l}" if dif_l > 0 else f"FALTANTE {dif_l}")
                lineas_texto.append(f"• {sku_l}: Esperado {esp_l} UN | Recibido {rec_l} UN ({est_l})")

            cuerpo_default = (
                f"Estimado equipo,\n\n"
                f"Se adjunta resumen del Acta Oficial de Recepción procesada en LUDIPEK WMS:\n\n"
                f"• Orden de Compra (PO): {oc_num}\n"
                f"• Proveedor: {prov_nom}\n"
                + (f"• Contenedor / Guía: {cont_ref}\n" if cont_ref else "")
                + f"• Fecha / Hora: {fecha_hoy}\n"
                f"• Total Esperado: {tot_esp} UN | Total Recibido: {tot_rec} UN (Diferencia: {dif_tot} UN)\n\n"
                f"Detalle por SKU:\n" + "\n".join(lineas_texto[:25]) + "\n\n"
                f"Saludos cordiales,\nTorre de Control LUDIPEK WMS"
            )

            txt_mail_para = texto_dark("Para (Correos separados por coma)", width=620, value=os.environ.get("WMS_EMAIL_DESTINO", "compras@ludipek.cl, logistica@ludipek.cl"))
            txt_mail_cc = texto_dark("CC (Opcional)", width=620, value="")
            txt_mail_asunto = texto_dark(
                "Asunto del Correo",
                width=620,
                value=f"Acta Oficial de Recepción PO {oc_num} - {prov_nom} | LUDIPEK WMS",
            )
            txt_mail_cuerpo = ft.TextField(
                label="Mensaje / Resumen de Conciliación",
                value=cuerpo_default,
                multiline=True,
                min_lines=7,
                max_lines=10,
                width=620,
                text_style=ft.TextStyle(size=11, color=TEXT_WHITE),
                bgcolor=BG_INPUT,
                border_color=BORDER_COLOR,
            )
            lbl_estado_mail = ft.Text(
                f"Archivo PDF generado: {os.path.basename(ruta_pdf_generado)}" if ruta_pdf_generado else "Resumen listo para enviar por correo.",
                size=11,
                color="#34D399",
            )

            def abrir_cliente_correo_mailto(ev=None):
                dest = (txt_mail_para.value or "").strip()
                cc = (txt_mail_cc.value or "").strip()
                subj = urllib.parse.quote(txt_mail_asunto.value or "")
                body = urllib.parse.quote(txt_mail_cuerpo.value or "")
                page.launch_url(f"mailto:{dest}?cc={cc}&subject={subj}&body={body}")
                dlg_correo.open = False
                page.update()
                notificar("Se abrió su cliente de correo con el resumen del Acta.", ACCENT_TEAL)

            def enviar_via_smtp_con_pdf(ev=None):
                dest_raw = (txt_mail_para.value or "").strip()
                if not dest_raw:
                    notificar("Ingrese al menos un destinatario en 'Para'.", "#D97706")
                    return

                smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
                smtp_port = int(os.environ.get("SMTP_PORT", "587"))
                smtp_user = os.environ.get("SMTP_USER", "")
                smtp_pass = os.environ.get("SMTP_PASS", "")

                if not smtp_user or not smtp_pass:
                    abrir_cliente_correo_mailto()
                    return

                try:
                    import smtplib
                    from email.message import EmailMessage

                    msg = EmailMessage()
                    msg["Subject"] = txt_mail_asunto.value or f"Acta Recepción PO {oc_num}"
                    msg["From"] = smtp_user
                    lista_para = [x.strip() for x in dest_raw.replace(";", ",").split(",") if x.strip()]
                    msg["To"] = ", ".join(lista_para)
                    if (txt_mail_cc.value or "").strip():
                        lista_cc = [x.strip() for x in txt_mail_cc.value.replace(";", ",").split(",") if x.strip()]
                        msg["Cc"] = ", ".join(lista_cc)
                    msg.set_content(txt_mail_cuerpo.value or "")

                    if ruta_pdf_generado and os.path.exists(ruta_pdf_generado):
                        with open(ruta_pdf_generado, "rb") as f_pdf:
                            msg.add_attachment(
                                f_pdf.read(),
                                maintype="application",
                                subtype="pdf",
                                filename=os.path.basename(ruta_pdf_generado),
                            )

                    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                        server.starttls()
                        server.login(smtp_user, smtp_pass)
                        server.send_message(msg)

                    dlg_correo.open = False
                    page.update()
                    notificar(f"Correo enviado con el Acta PDF adjunta a {', '.join(lista_para)}.", "#047857")
                except Exception as ex_smtp:
                    lbl_estado_mail.value = f"Aviso SMTP ({ex_smtp}). Abriendo cliente de correo..."
                    lbl_estado_mail.color = "#F87171"
                    page.update()
                    abrir_cliente_correo_mailto()

            dlg_correo = ft.AlertDialog(
                modal=True,
                bgcolor="#1E293B",
                title=ft.Row(
                    [
                        ft.Icon(ft.Icons.MARK_EMAIL_READ_ROUNDED, color=ACCENT_CYAN, size=24),
                        ft.Text(f"Enviar Acta Oficial por Correo (PO {oc_num})", size=16, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ],
                    spacing=8,
                ),
                content=ft.Container(
                    width=640,
                    content=ft.Column([txt_mail_para, txt_mail_cc, txt_mail_asunto, txt_mail_cuerpo, lbl_estado_mail], spacing=8, tight=True),
                ),
                actions=[
                    ft.TextButton("CERRAR", on_click=lambda e: (setattr(dlg_correo, "open", False), page.update())),
                    boton_primario("ABRIR EN OUTLOOK / CORREO", ft.Icons.OPEN_IN_NEW_ROUNDED, abrir_cliente_correo_mailto, ACCENT_BLUE, height_val=34),
                    boton_primario("ENVIAR CORREO (PDF ADJUNTO)", ft.Icons.SEND_ROUNDED, enviar_via_smtp_con_pdf, "#047857", height_val=34),
                ],
                actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
            page.overlay.append(dlg_correo)
            dlg_correo.open = True
            page.update()

        def click_exportar_pdf_recepcion(e=None):
            if not filas_conciliacion_export and not recepciones_asn_actual:
                notificar("No hay datos de recepción activos para exportar a PDF.", "#D97706")
                return
            try:
                ruta = generar_acta_recepcion_pdf(cabecera_asn_actual, filas_conciliacion_export, recepciones_asn_actual)
                descargar_o_abrir_archivo(self.page, ruta)
                notificar(f"Acta de Recepción de PO generada: {ruta}", "#047857")
                abrir_modal_enviar_correo_acta(cabecera_asn_actual, filas_conciliacion_export, ruta)
            except Exception as ex:
                notificar(f"Error generando PDF: {ex}", "#B91C1C")                


        def click_exportar_excel_recepcion(e=None):
            if not filas_conciliacion_export and not recepciones_asn_actual:
                notificar("No hay datos de recepción activos para exportar a Excel.", "#D97706")
                return
            try:
                res_mae = supabase.table("maestra_sku").select("sku, descripcion, multiplo").execute()
                mapa_desc = {str(m.get("sku", "")).strip().upper(): str(m.get("descripcion") or "") for m in (res_mae.data or []) if str(m.get("sku", "")).strip().upper()}
                mapa_mult = {str(m.get("sku", "")).strip().upper(): max(1, int(m.get("multiplo") or 1)) for m in (res_mae.data or []) if str(m.get("sku", "")).strip().upper()}

                for f in filas_conciliacion_export:
                    s_f = str(f.get("sku", "")).strip().upper()
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
                    fecha_fmt = fecha_raw if fecha_raw and fecha_raw not in ("None", "S/F") else "S/F"
                    if fecha_fmt != "S/F":
                        for fmt_in in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
                            try:
                                fecha_fmt = datetime.strptime(fecha_fmt, fmt_in).strftime("%d-%m-%Y")
                                break
                            except ValueError:
                                continue

                    clave = (sku_r, lote_limpio, fecha_fmt)
                    if clave not in agrupado_excel:
                        agrupado_excel[clave] = {"packs": 0, "unidades": 0}
                    agrupado_excel[clave]["packs"] += int(r.get("cajas") or 0)
                    agrupado_excel[clave]["unidades"] += int(r.get("unidades_totales") or 0)

                filas_excel = []
                for (sku_k, lote_k, fecha_k), totales in sorted(agrupado_excel.items(), key=lambda x: (x[0][0], x[0][1])):
                    unid_tot, packs_tot = totales["unidades"], totales["packs"]
                    if packs_tot == 0 and unid_tot > 0:
                        packs_tot = unid_tot // mapa_mult.get(sku_k, 1) if mapa_mult.get(sku_k, 1) > 1 else unid_tot
                    lote_fecha_str = f"{lote_k} - {fecha_k}" if (lote_k != "S/L" and fecha_k != "S/F") else (lote_k if lote_k != "S/L" else fecha_k)
                    filas_excel.append(
                        {
                            "SKU": sku_k,
                            "Descripcion": mapa_desc.get(sku_k, "Ingreso Directo"),
                            "Cantidad (Pack)": packs_tot,
                            "Lote": lote_k,
                            "LOTE FECHA": lote_fecha_str,
                            "Fecha": fecha_k,
                            "Cantidad (Unidades)": unid_tot,
                        }
                    )

                if not filas_excel and filas_conciliacion_export:
                    for f in filas_conciliacion_export:
                        sku_f = str(f.get("sku", "")).strip().upper()
                        filas_excel.append(
                            {
                                "SKU": sku_f,
                                "Descripcion": mapa_desc.get(sku_f, str(f.get("descripcion", ""))),
                                "Cantidad (Pack)": int(f.get("cajas_esperadas") or 0),
                                "Lote": "S/L",
                                "LOTE FECHA": "S/L",
                                "Fecha": "S/F",
                                "Cantidad (Unidades)": int(f.get("unidades_esperadas") or 0),
                            }
                        )

                df_final = pd.DataFrame(filas_excel, columns=["SKU", "Descripcion", "Cantidad (Pack)", "Lote", "LOTE FECHA", "Fecha", "Cantidad (Unidades)"])
                os.makedirs("reportes_recepcion", exist_ok=True)
                codigo_po = formatear_nombre_po(cabecera_asn_actual.get("numero_oc") or cabecera_asn_actual.get("codigo_asn") or "LIBRE")
                nombre_archivo = os.path.join("reportes_recepcion", f"PO_{codigo_po}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
                df_final.to_excel(nombre_archivo, index=False)
                descargar_o_abrir_archivo(self.page, nombre_archivo)
                notificar(f"Reporte Excel PO {codigo_po} generado.", "#047857")
            except Exception as ex:
                notificar(f"Error generando Excel: {ex}", "#B91C1C")

        def exportar_csv_recepcion_netsuite(e=None) -> str:
            if not filas_conciliacion_export and not recepciones_asn_actual:
                notificar("No hay datos para generar el CSV.", "#D97706")
                return ""
            os.makedirs("reportes_recepcion", exist_ok=True)
            oc_actual = str(cabecera_asn_actual.get("numero_oc") or "").strip()
            cod_po = formatear_nombre_po(cabecera_asn_actual.get("codigo_asn", "SIN-PO"))
            if not oc_actual or oc_actual == "S/OC":
                oc_actual = cod_po.removeprefix("PO-").removeprefix("ASN-").strip()

            recibido_por_sku = {}
            for r in recepciones_asn_actual:
                sku_r = str(r.get("sku", "")).strip().upper()
                unid_r = int(r.get("unidades_totales") or 0)
                if sku_r and unid_r > 0:
                    recibido_por_sku[sku_r] = recibido_por_sku.get(sku_r, 0) + unid_r

            if not recibido_por_sku:
                notificar("0 unidades físicas recibidas.", "#D97706")
                return ""

            oc_limpia = formatear_nombre_po(oc_actual)
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
            descargar_o_abrir_archivo(self.page, ruta_csv)
            notificar("CSV Item Receipt generado.", "#047857")
            return ruta_csv

        def descargar_po_netsuite_inbound(e=None):
            po_input = (txt_po_netsuite.value or "").strip().upper()
            if not po_input:
                notificar("Ingrese un número de PO (Ej: 1076) para consultar.", "#D97706")
                return

            # Extraer solo el número limpio por si escribieron "PO-1076" o "OC1076"
            po_num_limpio = po_input.replace("PO-", "").replace("OC-", "").replace("PO", "").replace("OC", "").strip()

            if not NETSUITE_CONECTADO:
                notificar("Módulo conexion_erp no activo. Verifique credenciales de NetSuite.", "#D97706")
                return

            notificar(f"Consultando información de la PO {po_num_limpio} en NetSuite...", ACCENT_CYAN)

            q_po = f"""
                SELECT
                    t.id AS po_internal_id,
                    t.tranid AS numero_oc,
                    TO_CHAR(t.trandate, 'YYYY-MM-DD') AS fecha_oc,
                    BUILTIN.DF(t.entity) AS proveedor,
                    BUILTIN.DF(t.status) AS estado_ns,
                    i.itemid AS sku,
                    BUILTIN.DF(i.id) AS descripcion,
                    ABS(tl.quantity) AS cantidad
                FROM transaction t
                INNER JOIN transactionline tl ON t.id = tl.transaction
                INNER JOIN item i ON tl.item = i.id
                WHERE t.type = 'PurchOrd'
                AND tl.mainline = 'F'
                AND (UPPER(t.tranid) = '{po_num_limpio}' OR UPPER(t.tranid) = 'PO{po_num_limpio}' OR UPPER(t.tranid) LIKE '%{po_num_limpio}')
                ORDER BY i.itemid ASC
            """
            try:
                df_po = consultar_netsuite(q_po)
            except Exception as ex_ns:
                notificar(f"Error consultando NetSuite: {ex_ns}", "#B91C1C")
                return

            if df_po is None or df_po.empty:
                notificar(f"No se encontró la PO '{po_input}' en NetSuite.", "#D97706")
                return

            # Agrupar SKUs y extraer datos de cabecera de la PO
            primera_fila = df_po.iloc[0]
            num_oc_real = str(primera_fila.get("numero_oc") or po_num_limpio).strip().upper()
            proveedor_str = str(primera_fila.get("proveedor") or "PROVEEDOR SIN NOMBRE").strip()
            fecha_oc_str = str(primera_fila.get("fecha_oc") or datetime.now().strftime("%Y-%m-%d")).strip()
            estado_ns_str = str(primera_fila.get("estado_ns") or "ABIERTA").strip()

            # Cargar múltiplos desde maestra_sku para calcular cajas esperadas
            mapa_multiplos = {}
            mapa_desc_maestra = {}
            try:
                res_m = supabase.table("maestra_sku").select("sku, multiplo, descripcion").limit(4000).execute()
                for m in (res_m.data or []):
                    s_k = str(m.get("sku") or "").strip().upper()
                    if s_k:
                        mapa_multiplos[s_k] = max(1, int(float(m.get("multiplo") or 1)))
                        if m.get("descripcion"):
                            mapa_desc_maestra[s_k] = str(m.get("descripcion")).strip()
            except Exception:
                pass

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
                notificar(f"La PO {num_oc_real} no contiene líneas de artículos válidas.", "#D97706")
                return

            total_skus = len(lista_lineas_po)
            total_unidades = sum(x["unidades_esperadas"] for x in lista_lineas_po)

            # Construir tabla visual de previsualización para el modal
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
                    cod_asn = f"ASN-PO-{num_oc_real}"
                    bodega_usr = getattr(page, "bodega_actual", "Bodega Santiago")

                    # 1. Verificar si ya existe en asn_cabecera o crearla
                    res_ex = supabase.table("asn_cabecera").select("id").eq("numero_oc", num_oc_real).limit(1).execute()
                    if res_ex.data:
                        asn_id_nuevo = res_ex.data[0]["id"]
                        supabase.table("asn_cabecera").update({
                            "proveedor": proveedor_str,
                            "estado": "EN_RECEPCION",
                        }).eq("id", asn_id_nuevo).execute()
                    else:
                        payload_cab = {
                            "codigo_asn": cod_asn,
                            "numero_oc": num_oc_real,
                            "proveedor": proveedor_str,
                            "fecha_esperada": fecha_oc_str,
                            "estado": "EN_RECEPCION",
                        }
                        try:
                            res_ins = supabase.table("asn_cabecera").insert({**payload_cab, "bodega": bodega_usr}).execute()
                        except Exception:
                            res_ins = supabase.table("asn_cabecera").insert(payload_cab).execute()
                        asn_id_nuevo = res_ins.data[0]["id"]

                    # 2. Sincronizar líneas en asn_detalle
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
                                "unidades_recibidas": 0,
                            })
                    if nuevas_lineas_bd:
                        supabase.table("asn_detalle").insert(nuevas_lineas_bd).execute()

                    # 3. Recargar selector y activar esta PO en pantalla
                    cargar_lista_asns()
                    dd_asn.value = str(asn_id_nuevo)
                    auditar_asn_seleccionado()
                    notificar(f"PO {num_oc_real} ({proveedor_str}) cargada y activa para recepción.", "#047857")
                except Exception as ex_save:
                    notificar(f"Error al activar PO {num_oc_real}: {ex_save}", "#B91C1C")

            dlg_confirmar_po = ft.AlertDialog(
                modal=True,
                bgcolor="#1E293B",
                title=ft.Row(
                    [
                        ft.Icon(ft.Icons.FACT_CHECK_ROUNDED, color=ACCENT_CYAN, size=24),
                        ft.Text(f"¿Desea utilizar la Orden de Compra PO {num_oc_real}?", size=16, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ],
                    spacing=8,
                ),
                content=ft.Container(
                    width=680,
                    height=380,
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
                                            f"N° OC: {num_oc_real}   |   Fecha OC: {fecha_oc_str}   |   Estado ERP: {estado_ns_str}",
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
                            ft.Text("DETALLE DE SKUs CONTENIDOS EN LA PO:", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
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
                        "SÍ, UTILIZAR ESTA PO (CARGAR AL WMS)",
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

            def cancelar_uso_po(ev):
                dlg_confirmar_po.open = False
                page.update()

            dlg_confirmar_po = ft.AlertDialog(
                modal=True,
                bgcolor="#1E293B",
                title=ft.Row(
                    [
                        ft.Icon(ft.Icons.FACT_CHECK_ROUNDED, color=ACCENT_CYAN, size=24),
                        ft.Text(f"¿Desea utilizar la Orden de Compra PO {num_oc_real}?", size=16, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ],
                    spacing=8,
                ),
                content=ft.Container(
                    width=680,
                    height=380,
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
                                            f"N° OC: {num_oc_real}   |   Fecha OC: {fecha_oc_str}   |   Estado ERP: {estado_ns_str}",
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
                            ft.Text("DETALLE DE SKUs CONTENIDOS EN LA PO:", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
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
                    ft.TextButton("CANCELAR", on_click=cancelar_uso_po),
                    boton_primario(
                        "SÍ, UTILIZAR ESTA PO (CARGAR AL WMS)",
                        ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                        confirmar_uso_po,
                        "#047857",
                        height_val=36,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )

            page.overlay.append(dlg_confirmar_po)
            dlg_confirmar_po.open = True
            page.update() 

        def cerrar_conciliacion_asn(e=None):
            try:
                ahora_cierre = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                cab_copia = dict(cabecera_asn_actual)
                lineas_copia = list(filas_conciliacion_export)
                ruta_pdf_cierre = None
                if filas_conciliacion_export or recepciones_asn_actual:
                    exportar_csv_recepcion_netsuite()
                    try:
                        ruta_pdf_cierre = generar_acta_recepcion_pdf(cabecera_asn_actual, filas_conciliacion_export, recepciones_asn_actual)
                        descargar_o_abrir_archivo(self.page, ruta_pdf_cierre)
                    except Exception:
                        pass
                if asn_actual_id:
                    supabase.table("asn_cabecera").update({"estado": "COMPLETADO"}).eq("id", asn_actual_id).execute()
                cargar_lista_asns()
                cargar_historico_recepciones()
                notificar(f"PO cerrada oficialmente ({ahora_cierre}).", "#047857")
                abrir_modal_enviar_correo_acta(cab_copia, lineas_copia, ruta_pdf_cierre)
            except Exception as ex:
                notificar(f"Error al cerrar PO: {ex}", "#B91C1C")

        def guardar_ajuste_linea_asn(e=None):
            sku_objetivo = (txt_nuevo_sku_po.value or dd_edit_sku_asn.value or "").strip().upper()
            if not asn_actual_id or not sku_objetivo:
                notificar("Seleccione una PO activa e indique el SKU.", "#D97706")
                return
            try:
                cajas_n = max(1, int(txt_edit_cajas_esp.value.strip() or "1"))
                mult_n = max(1, int(txt_edit_mult_esp.value.strip() or "1"))
                linea_existente = next((l for l in lineas_asn_actual if str(l["sku"]).upper() == sku_objetivo), None)
                datos_linea = {
                    "asn_id": asn_actual_id,
                    "sku": sku_objetivo,
                    "descripcion_proveedor": (txt_edit_desc_po.value or "Artículo PO").strip(),
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
                    notificar(f"SKU {sku_objetivo} agregado a la PO.", "#047857")
                auditar_asn_seleccionado()
            except Exception as ex:
                notificar(f"Error guardando línea: {ex}", "#B91C1C")

        def eliminar_linea_po_seleccionada(e=None):
            if not asn_actual_id or not dd_edit_sku_asn.value:
                return
            try:
                supabase.table("asn_detalle").delete().eq("asn_id", asn_actual_id).eq("sku", dd_edit_sku_asn.value).execute()
                notificar("SKU eliminado de la PO.", "#047857")
                auditar_asn_seleccionado()
            except Exception as ex:
                notificar(f"Error eliminando SKU: {ex}", "#B91C1C")

        def guardar_modificacion_lpn_fisico(e=None):
            if not dd_edit_lpn_id.value:
                return
            try:
                cajas_n = max(0, int(txt_mod_lpn_cajas.value.strip() or "0"))
                mult_n = max(1, int(txt_mod_lpn_mult.value.strip() or "1"))
                sueltas_n = max(0, int(txt_mod_lpn_sueltas.value.strip() or "0"))
                supabase.table("registro_recepcion").update(
                    {
                        "lpn": (txt_mod_lpn_cod.value or "").strip().upper(),
                        "sku": (txt_mod_lpn_sku.value or "").strip().upper(),
                        "cajas": cajas_n,
                        "multiplo_aplicado": mult_n,
                        "unidades_sueltas": sueltas_n,
                        "unidades_totales": max(1, int(txt_mod_lpn_totales.value.strip() or str((cajas_n * mult_n) + sueltas_n))),
                        "lote": formatear_lote_con_qa((txt_mod_lpn_lote.value or "S/L").strip().upper(), dd_mod_lpn_qa.value or "APROBADO"),
                        "fecha_vencimiento_cl": normalizar_fecha_sql(txt_mod_lpn_venc.value),
                    }
                ).eq("id", int(dd_edit_lpn_id.value)).execute()
                notificar("LPN modificado exitosamente.", "#047857")
                auditar_asn_seleccionado()
            except Exception as ex:
                notificar(f"Error modificando LPN: {ex}", "#B91C1C")

        def eliminar_lpn_fisico(e=None):
            if not dd_edit_lpn_id.value:
                return
            try:
                supabase.table("registro_recepcion").delete().eq("id", int(dd_edit_lpn_id.value)).execute()
                notificar("Registro LPN eliminado.", "#047857")
                dd_edit_lpn_id.value = None
                auditar_asn_seleccionado()
            except Exception as ex:
                notificar(f"Error eliminando LPN: {ex}", "#B91C1C")

        async def generar_json_con_gemini(archivo_remoto, prompt: str):
            modelos_preferidos = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash-exp"]
            ultimo_error = None
            for nombre_mod in modelos_preferidos:
                try:
                    resultado = ai_client.models.generate_content(
                        model=nombre_mod,
                        contents=[archivo_remoto, prompt],
                        config=types.GenerateContentConfig(response_mime_type="application/json"),
                    )
                    if inspect.iscoroutine(resultado):
                        resultado = await resultado
                    return resultado
                except Exception as err:
                    ultimo_error = err
                    continue
            raise ultimo_error

        async def seleccionar_y_procesar_packing_ia(e=None):
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            ruta_pdf = filedialog.askopenfilename(title="Seleccionar Packing List PDF", filetypes=[("Archivos PDF", "*.pdf")])
            root.destroy()
            if not ruta_pdf:
                return
            if not ai_client:
                notificar("Cliente IA no configurado.", "#D97706")
                return

            nombre_archivo = os.path.basename(ruta_pdf)
            txt_estado_ia.value = f"Procesando Packing List '{nombre_archivo}' con IA..."
            self.page.update()

            archivo_remoto = None
            try:
                archivo_remoto = ai_client.files.upload(file=ruta_pdf)
                if inspect.iscoroutine(archivo_remoto):
                    archivo_remoto = await archivo_remoto

                prompt = (
                    "Actúa como un especialista en comercio exterior y WMS. "
                    "Extrae los datos del Packing List adjunto en un JSON estricto. "
                    "Si NO hay código SKU explícito, CREA un código SKU identificatorio basado en la descripción del producto. "
                    "Si un SKU tiene múltiples lotes o fechas de vencimiento, únelos separados por coma en la misma línea. "
                    '{"proveedor": "Nombre proveedor", "orden": "Numero orden", "contenedor_referencia": "Codigo", "fecha_documento": "YYYY-MM-DD", "pallets_esperados": 1, "lineas": [{"sku": "SKU", "descripcion": "Nombre", "cajas_esperadas": 10, "multiplo_empaque": 12, "unidades_esperadas": 120, "lote_sugerido": "S/L", "vencimiento_sugerido_cl": "YYYY-MM-DD"}]}'
                )
                resp = await generar_json_con_gemini(archivo_remoto, prompt)
                if inspect.iscoroutine(resp):
                    resp = await resp

                texto_limpio = resp.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                datos_brutos = json.loads(texto_limpio)
                datos = datos_brutos[0] if isinstance(datos_brutos, list) and datos_brutos else (datos_brutos if isinstance(datos_brutos, dict) else {})

                mapa_skus = {}
                for l in datos.get("lineas", []):
                    sku_limpio = str(l.get("sku", "")).strip().upper()
                    if not sku_limpio:
                        continue

                    cajas = max(1, int(l.get("cajas_esperadas") or 1))
                    unid = max(cajas, int(l.get("unidades_esperadas") or cajas))
                    mult = int(l.get("multiplo_empaque") or max(1, unid // cajas))
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
                        if lt.strip() and lt.strip() != "S/L":
                            mapa_skus[sku_limpio]["lotes"].add(lt.strip())
                    for v in venc_sug.split(","):
                        if v.strip() and v.strip() not in ("NONE", "NULL"):
                            mapa_skus[sku_limpio]["vencimientos"].add(v.strip())

                    existe_sku = supabase.table("maestra_sku").select("sku").eq("sku", sku_limpio).execute()
                    if not existe_sku.data:
                        supabase.table("maestra_sku").insert(
                            {
                                "sku": sku_limpio,
                                "codigo_barras": sku_limpio,
                                "descripcion": l.get("descripcion", "SKU Inbound"),
                                "marca": str(datos.get("proveedor", "IMPORTADO")).upper()[:20],
                                "multiplo": mult,
                            }
                        ).execute()

                if asn_actual_id is not None and dd_asn.value != "LIBRES":
                    skus_actualizados = 0
                    for sku, info in mapa_skus.items():
                        lotes_finales = ", ".join(sorted(info["lotes"])) if info["lotes"] else "S/L"
                        venc_finales = ", ".join(sorted(info["vencimientos"])) if info["vencimientos"] else None

                        res_upd = (
                            supabase.table("asn_detalle")
                            .update(
                                {
                                    "cajas_esperadas": info["cajas"],
                                    "lote_sugerido": lotes_finales,
                                    "vencimiento_sugerido_cl": venc_finales,
                                }
                            )
                            .eq("asn_id", asn_actual_id)
                            .eq("sku", sku)
                            .execute()
                        )
                        if res_upd.data:
                            skus_actualizados += 1

                    upd_cab = {"archivo_origen": f"PO_NETSUITE + {nombre_archivo}"}
                    if datos.get("contenedor_referencia"):
                        upd_cab["contenedor_referencia"] = str(datos.get("contenedor_referencia")).strip().upper()
                    supabase.table("asn_cabecera").update(upd_cab).eq("id", asn_actual_id).execute()

                    txt_estado_ia.value = f"Cruce 3-Way exitoso: {skus_actualizados} SKUs de la PO enriquecidos."
                else:
                    cab = {
                        "codigo_asn": f"PO-{datos.get('orden', datetime.now().strftime('%H%M%S'))}",
                        "proveedor": datos.get("proveedor", "PROVEEDOR"),
                        "numero_oc": str(datos.get("orden", "")),
                        "contenedor_referencia": str(datos.get("contenedor_referencia") or (txt_contenedor.value or "")).strip().upper(),
                        "fecha_documento": datos.get("fecha_documento", ""),
                        "pallets_esperados": int(datos.get("pallets_esperados") or 1),
                        "archivo_origen": nombre_archivo,
                        "estado": "EN_RECEPCION",
                    }
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
                                "cajas_esperadas": info["cajas"],
                                "unidades_esperadas": info["unidades"],
                                "lote_sugerido": lotes_finales,
                                "vencimiento_sugerido_cl": venc_finales,
                            }
                        )

                    if detalles:
                        supabase.table("asn_detalle").insert(detalles).execute()

                    txt_estado_ia.value = f"PO creada desde Packing List: {len(detalles)} SKUs habilitados."
                    dd_asn.value = str(nuevo_id)

                cargar_lista_asns()
                auditar_asn_seleccionado()
            except Exception as ex:
                txt_estado_ia.value = f"Error procesando Packing List: {ex}"
            finally:
                if archivo_remoto:
                    try:
                        borrado = ai_client.files.delete(name=archivo_remoto.name)
                        if inspect.iscoroutine(borrado):
                            await borrado
                    except Exception:
                        pass
                self.page.update()

        async def anexar_certificado_coa_ia(e=None):
            if not ai_client:
                notificar("Cliente IA no configurado.", "#D97706")
                return
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            ruta_pdf = filedialog.askopenfilename(title="Seleccionar Certificado CoA", filetypes=[("Documentos", "*.pdf *.png *.jpg *.jpeg")])
            root.destroy()
            if not ruta_pdf:
                return

            nombre_coa = os.path.basename(ruta_pdf)
            txt_estado_ia.value = f"Extrayendo Lotes y Vencimientos desde '{nombre_coa}'..."
            self.page.update()

            archivo_remoto = None
            try:
                archivo_remoto = ai_client.files.upload(file=ruta_pdf)
                if inspect.iscoroutine(archivo_remoto):
                    archivo_remoto = await archivo_remoto

                prompt = (
                    "Extrae todos los SKUs con sus numeros de Lote y Fechas de Vencimiento. "
                    "Devuelve la información en formato JSON estricto: "
                    '{"lotes_vencimientos": [{"sku": "SKU", "lote": "LOTE1, LOTE2", "vencimiento_cl": "YYYY-MM-DD, YYYY-MM-DD"}]}'
                )
                resp = await generar_json_con_gemini(archivo_remoto, prompt)
                if inspect.iscoroutine(resp):
                    resp = await resp

                texto_limpio = resp.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                datos = json.loads(texto_limpio)

                mapa_skus = {}
                for item in datos.get("lotes_vencimientos", []):
                    sku_doc = str(item.get("sku", "")).strip().upper()
                    if not sku_doc:
                        continue
                    lote_doc = str(item.get("lote") or "S/L").strip().upper()
                    venc_doc = str(item.get("vencimiento_cl") or "").strip()
                    if sku_doc not in mapa_skus:
                        mapa_skus[sku_doc] = {"lotes": set(), "vencimientos": set()}
                    for l in lote_doc.split(","):
                        if l.strip() and l.strip() != "S/L":
                            mapa_skus[sku_doc]["lotes"].add(l.strip())
                    for v in venc_doc.split(","):
                        if v.strip() and v.strip() not in ("NONE", "NULL"):
                            mapa_skus[sku_doc]["vencimientos"].add(v.strip())

                actualizados = 0
                for sku, info in mapa_skus.items():
                    lotes_finales = ", ".join(sorted(info["lotes"])) if info["lotes"] else "S/L"
                    venc_finales = ", ".join(sorted(info["vencimientos"])) if info["vencimientos"] else None
                    supabase.table("asn_detalle").update(
                        {"lote_sugerido": lotes_finales, "vencimiento_sugerido_cl": venc_finales}
                    ).eq("asn_id", asn_actual_id).eq("sku", sku).execute()
                    actualizados += 1

                txt_estado_ia.value = f"Certificado CoA procesado: {actualizados} SKUs actualizados en la PO."
                auditar_asn_seleccionado()
            except Exception as ex:
                txt_estado_ia.value = f"Error leyendo Certificado CoA: {ex}"
            finally:
                if archivo_remoto:
                    try:
                        borrado = ai_client.files.delete(name=archivo_remoto.name)
                        if inspect.iscoroutine(borrado):
                            await borrado
                    except Exception:
                        pass
                self.page.update()

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

        # Conectar el dropdown afuera de la función para que se ejecute al seleccionar una opción
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

        # --- 5. VINCULACIÓN DE EVENTOS A CONTROLES ---
        txt_mod_lpn_cajas.on_change = recalcular_mod_lpn_totales
        txt_mod_lpn_mult.on_change = recalcular_mod_lpn_totales
        txt_mod_lpn_sueltas.on_change = recalcular_mod_lpn_totales
        txt_edit_cajas_esp.on_change = recalcular_mod_po_unidades
        txt_edit_mult_esp.on_change = recalcular_mod_po_unidades
        dd_edit_sku_asn.on_select = prellenar_edicion_linea_asn
        dd_edit_lpn_id.on_select = prellenar_edicion_lpn_fisico
        dd_qa_po_base.on_select = lambda e: (setattr(dd_asn, "value", dd_qa_po_base.value), auditar_asn_seleccionado()) if dd_qa_po_base.value and dd_qa_po_base.value != dd_asn.value else None
        dd_mod_po_base.on_select = lambda e: (setattr(dd_asn, "value", dd_mod_po_base.value), auditar_asn_seleccionado()) if dd_mod_po_base.value and dd_mod_po_base.value != dd_asn.value else None
        dd_asn.on_select = auditar_asn_seleccionado
        dd_fecha_hist_rec.on_select = cargar_historico_recepciones
        txt_buscar_hist_rec.on_change = cargar_historico_recepciones
        txt_fecha_hist_rec.on_change = cargar_historico_recepciones
        btn_guardar_contenedor.on_click = guardar_contenedor_db
        sw_auto_sync_rf.on_change = toggle_auto_sync_inbound
        txt_po_netsuite.on_submit = descargar_po_netsuite_inbound

        # --- 6. COMPOSICIÓN DE VISTAS (ARMADO FINAL DE LA INTERFAZ) ---
        barra_titulo_monitor = ft.Container(
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            bgcolor="#222A2C",
            border_radius=8,
            border=ft.Border.all(1, BORDER_COLOR),
            content=ft.Column(
                [
                    ft.Row(
                                [
                                    txt_po_netsuite,
                                    boton_primario(
                                        "LLAMAR PO",
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
                                ],
                                spacing=8,
                                wrap=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
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
                    ft.Text("Indicadores físicos de conciliación por partida (PO)", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Row(
                        [
                            crear_caja_digital(lbl_inb_cajas, "Cajas (Fís/PO)", ACCENT_TEAL, 86),
                            crear_caja_digital(lbl_inb_unidades, "Unid. Recibidas", ACCENT_BLUE, 86),
                            crear_caja_digital(lbl_inb_pallets, "LPNs Activos", "#D97706", 78),
                            crear_caja_digital(lbl_inb_avance, "Avance PO", "#10B981", 78),
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

        # PANEL 1: Solo aquí aparece barra_titulo_monitor ("KPI RECEPCIÓN & CONCILIACIÓN 3-WAY MATCH")
        subvista_inb_recepcion = ft.Column(
            [
                barra_titulo_monitor,
                ft.Row([panel_relojes_izquierdo, panel_grafico_derecho], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text("Detalle de órdenes y conciliación 3-Way Match por partida (PO vs Recepción RF)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                                    ft.Row(
                                        [
                                            sw_auto_sync_rf,
                                            boton_primario("ACTA PDF", ft.Icons.PICTURE_AS_PDF_OUTLINED, click_exportar_pdf_recepcion, ACCENT_TEAL, height_val=30),
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

        # PANEL 2: Consultor Histórico separado por Día de Recepción y con N° PO Real
        subvista_inb_consultas = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text("2. CONSULTOR HISTÓRICO DE RECEPCIONES POR DÍA Y PO REAL", size=14, weight=ft.FontWeight.W_900, color=TEXT_WHITE),
                                    ft.Text("Si una misma PO se recepciona en 2 o más días distintos, cada día aparece desglosado por separado.", size=11, color=TEXT_MUTED),
                                ],
                                spacing=2,
                            ),
                            ft.Row(
                                [
                                    dd_fecha_hist_rec,
                                    txt_fecha_hist_rec,
                                    txt_buscar_hist_rec,
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
                    ft.Text("DESGLOSE RÁPIDO POR DÍA DE RECEPCIÓN Y N° DE PO (CLIC PARA FILTRAR DÍA):", size=10, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
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
                            boton_primario("LIBERAR TODA LA PO", ft.Icons.DONE_ALL_ROUNDED, aplicar_qa_masivo_toda_la_po, ACCENT_TEAL),
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

        # PANEL 4: Modificación de PO y LPNs (con su propio selector de PO)
        subvista_inb_modificacion = ft.Column(
            [
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text("4.1 MODIFICACIÓN DOCUMENTAL DE LÍNEAS DE LA ORDEN DE COMPRA (PO)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
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
                                    boton_primario("GUARDAR EN PO", ft.Icons.SAVE_OUTLINED, guardar_ajuste_linea_asn, ACCENT_TEAL),
                                    boton_primario("ELIMINAR LÍNEA", ft.Icons.DELETE_OUTLINE, eliminar_linea_po_seleccionada, "#B91C1C"),
                                ],
                                wrap=True,
                                spacing=8,
                            ),
                        ],
                        spacing=8,
                    )
                ),
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Text("4.2 MODIFICACIÓN DE PALLETS FÍSICOS (LPNs) INGRESADOS", size=13, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
                            ft.Divider(color=BORDER_COLOR, height=1),
                            ft.Row(
                                [dd_edit_lpn_id, txt_mod_lpn_cod, txt_mod_lpn_sku, txt_mod_lpn_cajas, txt_mod_lpn_mult, txt_mod_lpn_sueltas, txt_mod_lpn_totales],
                                wrap=True,
                                spacing=8,
                            ),
                            ft.Row(
                                [
                                    txt_mod_lpn_lote,
                                    txt_mod_lpn_venc,
                                    dd_mod_lpn_qa,
                                    boton_primario("GUARDAR CAMBIOS EN LPN", ft.Icons.SAVE_AS_OUTLINED, guardar_modificacion_lpn_fisico, "#047857"),
                                    boton_primario("ELIMINAR LPN", ft.Icons.DELETE_FOREVER_OUTLINED, eliminar_lpn_fisico, "#B91C1C"),
                                ],
                                wrap=True,
                                spacing=8,
                            ),
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