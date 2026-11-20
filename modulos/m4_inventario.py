import os
import re
import json
import asyncio
import threading
from datetime import datetime
import pandas as pd
import flet as ft
from dependencias import *


def clave_inventario_wms(fila: dict) -> tuple:
 return (normalizar_bodega(fila.get("bodega")), str(fila.get("ubicacion_id") or fila.get("codigo_ubicacion") or "").upper(), str(fila.get("lpn_origen") or fila.get("lpn") or "S/LPN").upper(), normalizar_sku(fila.get("sku")), normalizar_lote(fila.get("lote")), fecha_a_iso(fila.get("fecha_vencimiento") or fila.get("fecha_vencimiento_cl")))

class InventarioModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables

        # --- 1. PALETA OSCURA DE DISEÑO INDUSTRIAL ---
        BG_MODULO = "#1B2122"
        BG_CARD = "#262E30"
        BG_INPUT = "#1D2426"
        BG_DIGITAL = "#121718"
        BORDER_COLOR = "#3B484B"
        ACCENT_TEAL = "#527976"
        ACCENT_CYAN = "#38BDF8"
        ACCENT_BLUE = "#0284C7"
        ACCENT_PURPLE = "#8B5CF6"
        ACCENT_AMBER = "#F59E0B"
        ACCENT_GREEN = "#10B981"
        TEXT_WHITE = "#FFFFFF"
        TEXT_MUTED = "#94A3B8"

        # --- 2. VARIABLES GLOBALES DE ESTADO ---
        datos_stock_wms = []
        mapa_stock_por_sku = {}
        mapa_ubicaciones_por_sku = {}
        mapa_sku_maestra = {}
        mapa_info_maestra = {}
        lista_usuarios_wms = []
        mapa_usuarios_wms = {}
        asignaciones_pasillo_db = []
        conteos_ubic_vacias_db = []
        conteos_ciclico_sku_db = []
        desvios_db = []
        subvista_activa_idx = 0

        # --- HELPER MULTI-BODEGA ---
        def obtener_bodega_actual() -> str:
            bod = str(getattr(self.page, "bodega_actual", "") or "").strip()
            return bod if bod in ("Bodega Santiago", "Bodega Concepcion") else "Bodega Santiago"

        # --- 3. FUNCIONES AUXILIARES UI ---
        def notificar(texto: str, color: str = "#0284C7"):
            from dependencias import notificar_global
            notificar_global(self.page, texto, color)

        def tarjeta_dark(contenido, padding=14, expand_val=None, height_val=None, width_val=None):
            t = ft.Container(
                content=contenido, padding=padding, height=height_val, width=width_val, expand=expand_val,
                bgcolor=BG_CARD, border_radius=8, border=ft.Border.all(1, BORDER_COLOR),
                shadow=ft.BoxShadow(blur_radius=10, color="#40000000", offset=ft.Offset(0, 3)),
            )
            if isinstance(self.tarjetas_adaptables, list):
                self.tarjetas_adaptables.append(t)
            return t

        def texto_dark(label: str, width: int = None, expand=None, value: str = "", on_change=None, icon=None):
            return ft.TextField(
                label=label, width=width, expand=expand, value=value, dense=True, text_size=12,
                color=TEXT_WHITE, bgcolor=BG_INPUT, border_color=BORDER_COLOR, focused_border_color=ACCENT_CYAN,
                label_style=ft.TextStyle(size=11, color=TEXT_MUTED),
                prefix_icon=icon,
                content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                on_change=on_change, border_radius=6,
            )

        def opt_w(key, text):
            return ft.DropdownOption(
                key=key, text=text,
                content=ft.Container(content=ft.Text(text, color=TEXT_WHITE, size=12), alignment=ft.Alignment.CENTER_LEFT),
            )

        def dropdown_dark(label: str, width: int = None, expand=None, value: str = None, options: list = None):
            return ft.Dropdown(
                label=label, width=width, expand=expand, value=value, options=options or [], dense=True,
                color=TEXT_WHITE, bgcolor=BG_INPUT, border_color=BORDER_COLOR, focused_border_color=ACCENT_CYAN,
                text_style=ft.TextStyle(size=12, color=TEXT_WHITE), label_style=ft.TextStyle(size=11, color=TEXT_MUTED),
                content_padding=ft.Padding.symmetric(horizontal=12, vertical=8), border_radius=6,
            )

        def crear_caja_digital(txt_control: ft.Text, etiqueta_inf: str, color_borde: str = "#6366F1", ancho: int = 88, tooltip: str = None):
            return ft.Column(
                [
                    ft.Container(
                        width=ancho, height=58, bgcolor=BG_DIGITAL, border_radius=6,
                        border=ft.Border.all(1.5, color_borde), alignment=ft.Alignment.CENTER,
                        shadow=ft.BoxShadow(blur_radius=6, color="#33000000"), content=txt_control,
                        tooltip=tooltip,
                    ),
                    ft.Text(etiqueta_inf, size=10, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4,
            )

        def formatear_fecha_hora(fh_str) -> str:
            if not fh_str or str(fh_str).strip() in ("None", "null", ""):
                return datetime.now().strftime("%Y-%m-%d %H:%M")
            try:
                dt = datetime.fromisoformat(str(fh_str).replace("Z", "+00:00"))
                if dt.tzinfo is not None:   # Supabase guarda en UTC: mostrar hora de Chile
                    try:
                        from zoneinfo import ZoneInfo
                        dt = dt.astimezone(ZoneInfo("America/Santiago"))
                    except Exception:
                        dt = dt.astimezone()
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                return str(fh_str)[:16]

        def resolver_nombre_usuario(valor_usr) -> str:
            if valor_usr is None:
                return "SIN ASIGNAR"
            clave = str(valor_usr).strip()
            if not clave or clave.upper() in ("NONE", "NULL", ""):
                return "SIN ASIGNAR"
            return mapa_usuarios_wms.get(clave.upper(), clave)

        # --- 4. CONTROLES ZONA 1: CONTROL INTEGRAL (ASIGNACIÓN DE PASILLOS Y CRUCE ERP) ---
        txt_buscar_inv = texto_dark("Buscar SKU o Descripción...", expand=True, icon=ft.Icons.SEARCH_ROUNDED)
        dd_racks_asignacion = dropdown_dark(
            label="Pasillo a Asignar", width=145, value="RACK A",
            options=[opt_w(f"RACK {L}", f"RACK {L}") for L in ("A", "B", "C", "D", "E", "F", "G", "H")],
        )
        dd_operador_asignar = dropdown_dark(
            label="Usuario Asignado (wms_usuarios)", width=250, value=None, options=[],
        )

        lbl_kpi_total_wms = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_kpi_total_erp = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color="#34D399", font_family="Consolas")
        lbl_kpi_dif_global = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color=ACCENT_AMBER, font_family="Consolas")
        lbl_kpi_avance_audi = ft.Text("0%", size=22, weight=ft.FontWeight.W_900, color=ACCENT_PURPLE, font_family="Consolas")

        lbl_estado_erp_cruce = ft.Text(
            "Módulo conexion_erp conectado. Cruce en vivo habilitado." if NETSUITE_CONECTADO else "Modo Cloud activo. Listo para cruce.",
            size=11, color="#34D399" if NETSUITE_CONECTADO else "#FBBF24",
        )

        tabla_asignacion_pasillos = ft.DataTable(
            heading_row_color=UI["card_alt"], heading_row_height=38, data_row_min_height=38, data_row_max_height=48,
            column_spacing=22, horizontal_margin=14, divider_thickness=0.5,
            columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in ['Tipo', 'Objetivo', 'Operador', 'Asignada', 'Avance', 'Estado', '']],
            rows=[],
        )

        tabla_cruce_erp_wms = ft.DataTable(
            heading_row_color=UI["card_alt"], heading_row_height=38, data_row_min_height=38, data_row_max_height=48,
            column_spacing=22, horizontal_margin=14, divider_thickness=0.5,
            columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in ['SKU', 'Descripción', 'NetSuite', 'WMS', 'Diferencia', 'Estado', '']],
            rows=[],
        )

        cont_asignacion = ui_tabla(tabla_asignacion_pasillos, 360)
        cont_cruce = ui_tabla(tabla_cruce_erp_wms, 480)

        # --- 5. CONTROLES ZONA 2: CONTEOS CÍCLICOS (SKU DIRIGIDO & UBICACIONES VACÍAS) ---
        txt_sku_dirigido = texto_dark("SKU a Dirigir (Ej: ALUC15)...", width=180, icon=ft.Icons.INVENTORY_2_OUTLINED)
        txt_ubic_sku_dirigido = texto_dark("Ubicación Sugerida (Opcional)", width=175, icon=ft.Icons.PLACE_OUTLINED)
        dd_operador_sku_dirigido = dropdown_dark(
            label="Asignar a Usuario (wms_usuarios)", width=240, value=None, options=[],
        )
        txt_Info_sku_dirigido = ft.Text("Escriba un SKU para ver su descripción y stock teórico actual en WMS.", size=11, color=TEXT_MUTED)

        txt_buscar_ciclico = texto_dark("Filtrar conteos por SKU, Ubicación o Usuario...", expand=True, icon=ft.Icons.SEARCH_ROUNDED)
        txt_buscar_vacias = texto_dark("Filtrar ubicaciones vacías por Código, Hallazgo o Usuario...", expand=True, icon=ft.Icons.SEARCH_ROUNDED)

        lbl_kpi_cic_total = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_kpi_cic_ok = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color=ACCENT_GREEN, font_family="Consolas")
        lbl_kpi_vac_total = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color=ACCENT_PURPLE, font_family="Consolas")
        lbl_kpi_vac_hallazgo = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color=ACCENT_AMBER, font_family="Consolas")

        tabla_ciclico_sku = ft.DataTable(
            heading_row_color=UI["card_alt"], heading_row_height=38, data_row_min_height=38, data_row_max_height=48,
            column_spacing=22, horizontal_margin=14, divider_thickness=0.5,
            columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in ['Fecha', 'SKU', 'Descripción', 'Ubicación', 'Sistema', 'Contado', 'Dif.', 'Operador', 'Estado', '']],
            rows=[],
        )

        tabla_ubicaciones_vacias = ft.DataTable(
            heading_row_color=UI["card_alt"], heading_row_height=38, data_row_min_height=38, data_row_max_height=48,
            column_spacing=22, horizontal_margin=14, divider_thickness=0.5,
            columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in ['Fecha', 'Ubicación', 'Resultado', 'LPN / SKU encontrado', 'Operador', 'Estado', '']],
            rows=[],
        )

        cont_tabla_ciclico = ui_tabla(tabla_ciclico_sku, 460)
        cont_tabla_vacias = ui_tabla(tabla_ubicaciones_vacias, 460)

        # --- 6. CONTROLES ZONA 3: TRAZABILIDAD (LPN HISTORY Y LOGS DE UBICACIÓN) ---
        txt_traz_buscar_lpn = texto_dark("Ingresar o Escanear Código LPN (Ej: LPN-100456)...", width=350, icon=ft.Icons.QR_CODE_2_ROUNDED)
        txt_traz_buscar_ubic = texto_dark("Ingresar Código de Ubicación (Ej: A-01-N2)...", width=350, icon=ft.Icons.LOCATION_ON_OUTLINED)

        lbl_traz_lpn_actual = ft.Text("LPN NO SELECCIONADO", size=15, weight=ft.FontWeight.W_900, color=TEXT_MUTED)
        lbl_traz_lpn_estado = ft.Text("INGRESE UN CÓDIGO", size=12, color=TEXT_MUTED)
        lbl_traz_ubic_actual = ft.Text("UBICACIÓN NO SELECCIONADA", size=15, weight=ft.FontWeight.W_900, color=TEXT_MUTED)

        tabla_trazabilidad_lpn = ft.DataTable(
            heading_row_color=UI["card_alt"], heading_row_height=38, data_row_min_height=38, data_row_max_height=48,
            column_spacing=22, horizontal_margin=14, divider_thickness=0.5,
            columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in ['Fecha', 'Evento', 'Desde', 'Hacia', 'Usuario', 'Resultado']],
            rows=[],
        )

        tabla_trazabilidad_ubic = ft.DataTable(
            heading_row_color=UI["card_alt"], heading_row_height=38, data_row_min_height=38, data_row_max_height=48,
            column_spacing=22, horizontal_margin=14, divider_thickness=0.5,
            columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in ['Fecha', 'LPN', 'SKU / lote', 'Acción', 'Usuario']],
            rows=[],
        )

        cont_traz_lpn = ui_tabla(tabla_trazabilidad_lpn, 420)
        cont_traz_ubic = ui_tabla(tabla_trazabilidad_ubic, 420)

        # --- 7. CONTROLES ZONA 4: AUDITORÍA EN PISO (DESVÍOS DE GRÚA) ---
        txt_buscar_desvios = texto_dark("Buscar LPN o SKU con desvío...", expand=True, icon=ft.Icons.SEARCH_ROUNDED)

        lbl_dig_desv_pendientes = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color="#F87171", font_family="Consolas")
        lbl_dig_desv_resueltos = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color="#34D399", font_family="Consolas")

        tabla_desvios_grua = ft.DataTable(
            heading_row_color=UI["card_alt"], heading_row_height=38, data_row_min_height=38, data_row_max_height=48,
            column_spacing=22, horizontal_margin=14, divider_thickness=0.5,
            columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in ['Fecha', 'LPN / SKU', 'Ubicación', 'Incidencia', 'Reportado por', 'Estado', '']],
            rows=[],
        )
        cont_desvios = ui_tabla(tabla_desvios_grua, 460)

        # --- 8. LÓGICA CORE Y SUPABASE (FILTRADO ESTRICTO MULTI-BODEGA) ---
        def cargar_usuarios_wms():
            nonlocal lista_usuarios_wms, mapa_usuarios_wms
            bodega_act = obtener_bodega_actual()
            nuevo_mapa = {}
            nueva_lista = []
            opciones_ops = []
            try:
                res = supabase.table("wms_usuarios").select("*").order("id").execute()
                filas_u = res.data or []
                for row in filas_u:
                    u_id = str(row.get("usuario") or row.get("rut") or row.get("id") or "").strip()
                    n_comp = str(row.get("nombre_completo") or row.get("nombre") or u_id).strip()
                    rol_u = str(row.get("rol") or "OPERADOR").strip()
                    bod_u = str(row.get("bodega") or "Bodega Santiago").strip()
                    if not u_id:
                        continue

                    etiqueta_mostrar = f"{u_id} - {n_comp}" if n_comp.upper() != u_id.upper() else u_id
                    nuevo_mapa[u_id.upper()] = etiqueta_mostrar
                    nuevo_mapa[n_comp.upper()] = etiqueta_mostrar
                    if row.get("id") is not None:
                        nuevo_mapa[str(row.get("id")).upper()] = etiqueta_mostrar

                    if row.get("activo") is False:
                        continue

                    # Filtrar el dropdown para que solo muestre operadores de la bodega activa (o ADMIN / AMBAS)
                    es_global = (
                        "ADMIN" in rol_u.upper()
                        or "AMBAS" in bod_u.upper()
                        or "TODAS" in bod_u.upper()
                    )
                    if not es_global and bod_u.upper() != bodega_act.upper():
                        continue

                    nueva_lista.append(row)
                    opciones_ops.append(opt_w(u_id, f"{etiqueta_mostrar} ({rol_u})"))
            except Exception:
                pass

            if not opciones_ops:
                usuario_sesion = getattr(self.page, "usuario_actual", "ADMIN")
                opciones_ops = [opt_w(str(usuario_sesion), str(usuario_sesion))]
                nuevo_mapa[str(usuario_sesion).upper()] = str(usuario_sesion)

            mapa_usuarios_wms = nuevo_mapa
            lista_usuarios_wms = nueva_lista
            dd_operador_asignar.options = list(opciones_ops)
            dd_operador_sku_dirigido.options = list(opciones_ops)
            llaves_validas = [o.key for o in opciones_ops]
            if llaves_validas:
                if not dd_operador_asignar.value or dd_operador_asignar.value not in llaves_validas:
                    dd_operador_asignar.value = llaves_validas[0]
                if not dd_operador_sku_dirigido.value or dd_operador_sku_dirigido.value not in llaves_validas:
                    dd_operador_sku_dirigido.value = llaves_validas[0]

        def sync_stock_inventario():
            nonlocal datos_stock_wms, mapa_sku_maestra, mapa_stock_por_sku, mapa_ubicaciones_por_sku, mapa_info_maestra
            bodega_act = obtener_bodega_actual()
            nuevo_stock_sku = {}
            nuevas_ubic_sku = {}
            nueva_maestra = {}

            def leer_paginado(nombre_tabla: str, max_reg: int = 4000, filtrar_bodega: bool = False) -> list:
                acum = []
                paso = 1000
                for off in range(0, max_reg, paso):
                    try:
                        q = supabase.table(nombre_tabla).select("*")
                        if filtrar_bodega:
                            q = q.eq("bodega", bodega_act)
                        res = q.range(off, off + paso - 1).execute()
                        lote = res.data or []
                        acum.extend(lote)
                        if len(lote) < paso:
                            break
                    except Exception:
                        break
                return acum

            try:
                # 1. Cargar Maestra de SKUs (Global para ambas bodegas)
                nueva_info = {}
                mapa_ean_a_sku.clear()
                for m in leer_paginado("maestra_sku", 4000, filtrar_bodega=False):
                    s_k = str(m.get("sku") or "").strip().upper()
                    if s_k:
                        nueva_maestra[s_k] = str(m.get("descripcion") or "")
                        ean = str(m.get("codigo_barras") or "").strip().upper()
                        info = nueva_info.setdefault(s_k, {"marca": m.get("marca"), "ean": ean, "multiplo": None})
                        mult = int(m.get("multiplo") or 1)
                        if mult > 1 and (info["multiplo"] is None or mult > info["multiplo"]):
                            info["multiplo"] = mult
                        if ean:
                            mapa_ean_a_sku[ean] = s_k
                mapa_info_maestra = nueva_info

                # 2. Cargar registro_recepcion filtrado por la bodega activa
                filas_rec = leer_paginado("registro_recepcion", 4000, filtrar_bodega=True)
                mapa_rec_lpn = {}
                for r in filas_rec:
                    lpn_k = str(r.get("lpn") or "").strip().upper()
                    if lpn_k:
                        mapa_rec_lpn[lpn_k] = r

                # 3. Leer bodega_inventario_ubicacion filtrado por la bodega activa
                ubicados_vistos = set()
                lpns_en_racks = set()

                filas_u = leer_paginado("bodega_inventario_ubicacion", 4000, filtrar_bodega=True)
                for r in filas_u:
                    ubi_r = str(r.get("codigo_ubicacion") or r.get("ubicacion") or r.get("posicion") or "").strip().upper()
                    lpn_r = str(r.get("lpn") or r.get("codigo_lpn") or r.get("pallet") or "").strip().upper()
                    sku_r = str(r.get("sku") or "").strip().upper()

                    if not lpn_r and not sku_r:
                        continue

                    info_lpn = mapa_rec_lpn.get(lpn_r, {})
                    sku_final = sku_r or str(info_lpn.get("sku") or "").strip().upper()
                    if not sku_final or sku_final in ("NONE", "NULL", "-"):
                        continue

                    raw_unid = (
                        r.get("cantidad_unidades")
                        if r.get("cantidad_unidades") is not None
                        else (
                            r.get("unidades")
                            if r.get("unidades") is not None
                            else (
                                r.get("unidades_totales")
                                if r.get("unidades_totales") is not None
                                else (
                                    r.get("cantidad")
                                    if r.get("cantidad") is not None
                                    else (
                                        r.get("stock")
                                        if r.get("stock") is not None
                                        else info_lpn.get("unidades_totales")
                                    )
                                )
                            )
                        )
                    )
                    try:
                        unid_val = int(float(raw_unid or 0))
                    except Exception:
                        unid_val = 0

                    if unid_val <= 0:
                        continue

                    clave_unica = (ubi_r or "RACK", lpn_r or f"{sku_final}_{r.get('id')}")
                    if clave_unica in ubicados_vistos:
                        continue
                    ubicados_vistos.add(clave_unica)
                    if lpn_r:
                        lpns_en_racks.add(lpn_r)

                    nuevo_stock_sku[sku_final] = nuevo_stock_sku.get(sku_final, 0) + unid_val
                    if ubi_r and ubi_r not in ("NONE", "NULL", ""):
                        if sku_final not in nuevas_ubic_sku:
                            nuevas_ubic_sku[sku_final] = set()
                        nuevas_ubic_sku[sku_final].add(ubi_r)

                # 4. Incluir LPNs recepcionados en Andén de la bodega activa que aún no están en rack
                lpns_anden_vistos = set()
                for r in filas_rec:
                    lpn_r = str(r.get("lpn") or "").strip().upper()
                    if not lpn_r or lpn_r in lpns_en_racks or lpn_r in lpns_anden_vistos:
                        continue
                    lpns_anden_vistos.add(lpn_r)
                    sku_r = str(r.get("sku") or "").strip().upper()
                    if not sku_r or sku_r in ("NONE", "NULL", "-"):
                        continue
                    try:
                        unid_r = int(float(r.get("unidades_totales") or r.get("unidades") or r.get("cantidad") or 0))
                    except Exception:
                        unid_r = 0
                    if unid_r <= 0:
                        continue

                    ubi_rec = str(r.get("ubicacion") or r.get("codigo_ubicacion") or "ANDÉN RECEPCIÓN").strip().upper()
                    nuevo_stock_sku[sku_r] = nuevo_stock_sku.get(sku_r, 0) + unid_r
                    if sku_r not in nuevas_ubic_sku:
                        nuevas_ubic_sku[sku_r] = set()
                    nuevas_ubic_sku[sku_r].add(ubi_rec)

                mapa_sku_maestra = nueva_maestra
                mapa_stock_por_sku = nuevo_stock_sku
                mapa_ubicaciones_por_sku = nuevas_ubic_sku
                datos_stock_wms = [{"sku": k, "unidades": v, "bodega": bodega_act} for k, v in sorted(nuevo_stock_sku.items())]
                lbl_kpi_total_wms.value = f"{sum(nuevo_stock_sku.values()):,}".replace(",", ".")
            except Exception as ex_s:
                print(f"[WARN] Error consolidando stock WMS ({bodega_act}): {ex_s}")

        def actualizar_preview_sku_dirigido(e=None):
            sku_in = (txt_sku_dirigido.value or "").strip().upper()
            if not sku_in:
                txt_Info_sku_dirigido.value = "Escriba un SKU para ver su descripción y stock teórico actual en WMS."
                txt_Info_sku_dirigido.color = TEXT_MUTED
                page.update()
                return
            desc = mapa_sku_maestra.get(sku_in, "SKU no registrado en maestra")
            st_teo = mapa_stock_por_sku.get(sku_in, 0)
            ubics = sorted(mapa_ubicaciones_por_sku.get(sku_in, set()))
            ubic_str = ", ".join(ubics[:4]) if ubics else "Sin ubicación registrada en esta bodega"
            if ubics and not (txt_ubic_sku_dirigido.value or "").strip():
                txt_ubic_sku_dirigido.value = ubics[0]
            txt_Info_sku_dirigido.value = f"📦 [{obtener_bodega_actual()}] {sku_in}: {desc}  |  Stock Teórico WMS: {st_teo} UN  |  Ubicaciones: {ubic_str}"
            txt_Info_sku_dirigido.color = ACCENT_CYAN
            page.update()

        txt_sku_dirigido.on_change = actualizar_preview_sku_dirigido

        # --- TAREAS DE CONTEO (pasillo completo, vacías de un pasillo o SKU dirigido) ---
        # Se guardan con la función wms_crear_tarea_conteo (script 09) y el celular las ve en "Mis tareas".
        tareas_conteo_db = []
        pasillos_bodega = {}

        TIPOS_TAREA = {
            "PASILLO": ("Contar pasillo", ft.Icons.VIEW_COLUMN_OUTLINED),
            "VACIAS": ("Auditar vacías", ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED),
            "SKU": ("Cíclico por SKU", ft.Icons.TRACK_CHANGES_ROUNDED),
        }

        def cargar_pasillos_bodega():
            nonlocal pasillos_bodega
            conteo = {}
            try:
                filas = leer_tabla_paginada(lambda: supabase.table("bodega_ubicaciones").select("codigo_ubicacion").eq("bodega", obtener_bodega_actual()))
                for f in filas:
                    cod = str(f.get("codigo_ubicacion") or "").strip().upper()
                    if "-" in cod and not cod.startswith("ZONA"):
                        p = cod.split("-")[0]
                        conteo[p] = conteo.get(p, 0) + 1
            except Exception as ex:
                print(f"[WARN] Pasillos: {ex}")
            pasillos_bodega = conteo
            dd_racks_asignacion.options = [opt_w(p, f"Pasillo {p}  ({n} ubic.)") for p, n in sorted(conteo.items())]
            if dd_racks_asignacion.value not in conteo:
                dd_racks_asignacion.value = next(iter(sorted(conteo)), None)

        def cambiar_tipo_tarea(e=None):
            tipo = dd_tipo_tarea.value or "PASILLO"
            dd_racks_asignacion.visible = tipo in ("PASILLO", "VACIAS")
            txt_sku_dirigido.visible = tipo == "SKU"
            txt_Info_sku_dirigido.visible = tipo == "SKU"
            page.update()

        def renderizar_asignaciones():
            filas = []
            abiertas = 0
            for t in tareas_conteo_db:
                est = str(t.get("estado") or "PENDIENTE").upper()
                tipo = str(t.get("tipo") or "PASILLO").upper()
                total = int(t.get("total") or 0)
                avance = int(t.get("avance") or 0)
                if est in ("PENDIENTE", "EN_PROCESO"):
                    abiertas += 1
                pct = min(1.0, avance / total) if total else (1.0 if est == "COMPLETADA" else 0.0)
                objetivo = f"Pasillo {t.get('pasillo')}" if tipo != "SKU" else f"{t.get('sku')} · {str(t.get('descripcion') or '')[:30]}"
                color_est = {"PENDIENTE": UI["texto_2"], "EN_PROCESO": UI["alerta"], "COMPLETADA": UI["exito"], "ANULADA": UI["peligro"]}.get(est, UI["texto_2"])
                acciones = []
                if est in ("PENDIENTE", "EN_PROCESO"):
                    acciones = [
                        ft.IconButton(icon=ft.Icons.TASK_ALT_ROUNDED, icon_color=UI["exito"], icon_size=20, tooltip="Marcar como completada",
                                      on_click=lambda e, i=t.get("id"): cerrar_tarea(i, "COMPLETADA")),
                        ft.IconButton(icon=ft.Icons.CLOSE_ROUNDED, icon_color=UI["texto_2"], icon_size=20, tooltip="Anular tarea",
                                      on_click=lambda e, i=t.get("id"): cerrar_tarea(i, "ANULADA")),
                    ]
                filas.append(ft.DataRow(cells=[
                    ft.DataCell(ft.Row([ft.Icon(TIPOS_TAREA.get(tipo, TIPOS_TAREA["PASILLO"])[1], size=16, color=UI["acento"]),
                                        ft.Text(TIPOS_TAREA.get(tipo, TIPOS_TAREA["PASILLO"])[0], size=12, color=UI["texto"])], spacing=6, tight=True)),
                    ft.DataCell(ft.Text(objetivo, size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"])),
                    ft.DataCell(ft.Text(resolver_nombre_usuario(t.get("usuario")), size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(formatear_fecha_hora(t.get("creada_en")), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Row([
                        ft.ProgressBar(value=pct, width=110, height=6, color=UI["exito"] if pct >= 1 else UI["acento"], bgcolor="#334044", border_radius=3),
                        ft.Text(f"{avance}/{total}", size=12, color=UI["texto_2"]),
                    ], spacing=8, tight=True)),
                    ft.DataCell(ft.Text(est.replace("_", " ").capitalize(), size=12, weight=ft.FontWeight.W_600, color=color_est)),
                    ft.DataCell(ft.Row(acciones, spacing=0, tight=True)),
                ]))
            tabla_asignacion_pasillos.rows = filas
            lbl_kpi_avance_audi.value = str(abiertas)

        def cargar_asignaciones_piso():
            nonlocal tareas_conteo_db
            try:
                res = supabase.rpc("wms_tareas_conteo", {"p_bodega": obtener_bodega_actual(), "p_usuario": None, "p_solo_abiertas": True}).execute()
                tareas_conteo_db = res.data or []
                lbl_aviso_tareas.visible = False
            except Exception as ex:
                tareas_conteo_db = []
                lbl_aviso_tareas.value = f"No se pudieron leer las tareas. ¿Se ejecutó el script 09_tareas_conteo.sql? ({ex})"
                lbl_aviso_tareas.visible = True
            renderizar_asignaciones()

        def asignar_operador_pasillo(e=None):
            tipo = dd_tipo_tarea.value or "PASILLO"
            usuario = dd_operador_asignar.value
            pasillo = dd_racks_asignacion.value if tipo != "SKU" else None
            sku = (txt_sku_dirigido.value or "").strip().upper() if tipo == "SKU" else None
            if not usuario:
                notificar("Seleccione el operador que hará el conteo.", "#D97706")
                return
            if tipo != "SKU" and not pasillo:
                notificar("Seleccione un pasillo.", "#D97706")
                return
            if tipo == "SKU" and not sku:
                notificar("Escriba el SKU a contar.", "#D97706")
                return
            try:
                supabase.rpc("wms_crear_tarea_conteo", {
                    "p_bodega": obtener_bodega_actual(), "p_tipo": tipo, "p_pasillo": pasillo, "p_sku": sku,
                    "p_usuario": usuario, "p_creado_por": str(getattr(self.page, "usuario_actual", None) or "PC"),
                }).execute()
            except Exception as ex:
                notificar(mensaje_error_wms(ex), "#B91C1C")
                return
            objetivo = f"pasillo {pasillo}" if tipo != "SKU" else f"SKU {sku}"
            notificar(f"Tarea asignada a {resolver_nombre_usuario(usuario)}: {TIPOS_TAREA[tipo][0].lower()} ({objetivo}). La verá en su celular.", "#047857")
            txt_sku_dirigido.value = ""
            cargar_asignaciones_piso()
            page.update()

        def cerrar_tarea(id_tarea, estado: str):
            try:
                supabase.rpc("wms_actualizar_tarea_conteo", {
                    "p_id": id_tarea, "p_estado": estado, "p_usuario": str(getattr(self.page, "usuario_actual", None) or "PC"),
                }).execute()
            except Exception as ex:
                notificar(mensaje_error_wms(ex), "#B91C1C")
                return
            cargar_asignaciones_piso()
            page.update()

        def mensaje_error_wms(ex) -> str:
            txt = str(getattr(ex, "message", None) or ex)
            if "WMS:" in txt:
                txt = txt.split("WMS:", 1)[1].split("'", 1)[0].split('"', 1)[0]
            return txt.strip()

        # --- 9. LÓGICA ZONA 2: AUDITORÍA CÍCLICA SKU DIRIGIDO & UBICACIONES VACÍAS ---
        def renderizar_tablas_auditorias_conteos(e=None):
            filtro_c = (txt_buscar_ciclico.value or "").strip().upper()
            filtro_v = (txt_buscar_vacias.value or "").strip().upper()

            # 1. Construir filas de auditoria_ciclico_sku
            nuevas_filas_cic = []
            cic_conciliados = 0

            for row_c in list(conteos_ciclico_sku_db):
                sku_c = str(row_c.get("sku") or row_c.get("codigo_sku") or "-").strip().upper()
                desc_c = str(row_c.get("descripcion") or mapa_sku_maestra.get(sku_c, "Producto en Conteo Cíclico"))
                ubi_c = str(
                    row_c.get("codigo_ubicacion")
                    or row_c.get("ubicacion")
                    or ", ".join(sorted(mapa_ubicaciones_por_sku.get(sku_c, set()))[:2])
                    or "MÚLTIPLES"
                ).strip().upper()

                teo_val = row_c.get("unidades_sistema")
                if teo_val is None:
                    teo_val = row_c.get("cantidad_esperada")
                if teo_val is None:
                    teo_val = row_c.get("stock_teorico")
                if teo_val is None:
                    teo_val = row_c.get("stock_sistema")
                if teo_val is None:
                    teo_val = mapa_stock_por_sku.get(sku_c, 0)
                teo_int = int(float(teo_val or 0))

                est_raw = str(row_c.get("estado") or row_c.get("estado_auditoria") or "").strip().upper()

                cont_raw = (
                    row_c.get("cantidad_contada")
                    if row_c.get("cantidad_contada") is not None
                    else (
                        row_c.get("conteo_fisico")
                        if row_c.get("conteo_fisico") is not None
                        else (
                            row_c.get("unidades_contadas")
                            if row_c.get("unidades_contadas") is not None
                            else row_c.get("cantidad")
                        )
                    )
                )
                tiene_conteo = cont_raw is not None and str(cont_raw).strip() not in ("", "None", "null")

                if tiene_conteo:
                    cont_int = int(float(cont_raw))
                    dif_int = cont_int - teo_int
                elif est_raw in ("CONFORME", "CONCILIADO", "CUADRADO OK", "APROBADO", "OK"):
                    tiene_conteo = True
                    cont_int = teo_int
                    dif_int = 0
                elif est_raw == "INCIDENCIA":
                    tiene_conteo = True
                    cont_int = 0
                    dif_int = -teo_int
                else:
                    cont_int = 0
                    dif_int = 0

                usr_raw = (
                    row_c.get("auditor")
                    or row_c.get("usuario")
                    or row_c.get("operador")
                    or row_c.get("usuario_asignado")
                    or row_c.get("creado_por")
                    or "SIN ASIGNAR"
                )
                usr_str = resolver_nombre_usuario(usr_raw)
                fecha_c = formatear_fecha_hora(row_c.get("fecha") or row_c.get("created_at") or row_c.get("fecha_conteo"))

                if not est_raw or est_raw == "SIN_REVISAR":
                    if not tiene_conteo:
                        est_raw = "SKU DIRIGIDO (PEND.)"
                    elif dif_int == 0:
                        est_raw = "CONFORME"
                    else:
                        est_raw = "INCIDENCIA"

                if est_raw in ("CONFORME", "CUADRADO OK", "CONCILIADO", "APROBADO", "OK", "COMPLETADO"):
                    cic_conciliados += 1
                    badge_est = crear_badge_estado(est_raw, "#065F46", "#D1FAE5")
                elif "PEND" in est_raw or "DIRIGIDO" in est_raw or "ASIGNADO" in est_raw:
                    badge_est = crear_badge_estado(est_raw, "#1E3A8A", "#DBEAFE")
                else:
                    badge_est = crear_badge_estado(est_raw, "#991B1B", "#FEE2E2")

                if filtro_c and not any(filtro_c in c_str.upper() for c_str in (sku_c, desc_c, ubi_c, usr_str, est_raw)):
                    continue

                def validar_ciclico(ev, r_item=row_c):
                    r_item["estado"] = "CONCILIADO"
                    r_item["estado_auditoria"] = "CONCILIADO"
                    if r_item.get("id") is not None:
                        for col_st in ("estado_auditoria", "estado"):
                            try:
                                supabase.table("auditoria_ciclico_sku").update({col_st: "CONCILIADO"}).eq("id", r_item["id"]).execute()
                                break
                            except Exception:
                                continue
                    notificar(f"Conteo cíclico de SKU {r_item.get('sku', '')} validado.", "#047857")
                    renderizar_tablas_auditorias_conteos()

                if est_raw == "INCIDENCIA" and cont_raw is None:
                    txt_conteo_rf = "INCIDENCIA RF"
                    txt_dif_str = "REVISAR"
                    col_dif = "#F87171"
                else:
                    txt_conteo_rf = f"{cont_int} UN" if tiene_conteo else "En espera RF"
                    txt_dif_str = f"{dif_int:+d} UN" if tiene_conteo else "PEND."
                    col_dif = "#34D399" if (tiene_conteo and dif_int == 0) else ("#F87171" if tiene_conteo else TEXT_MUTED)

                nuevas_filas_cic.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(fecha_c, size=11, color=UI["texto_2"])),
                            ft.DataCell(ft.Text(sku_c, weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                            ft.DataCell(ft.Text(desc_c[:48], size=12, color=UI["texto"])),
                            ft.DataCell(ft.Text(ubi_c, weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                            ft.DataCell(ft.Text(f"{teo_int} UN", size=12, color=UI["texto_2"])),
                            ft.DataCell(ft.Text(txt_conteo_rf, weight=ft.FontWeight.BOLD, size=12, color="#F87171" if est_raw == "INCIDENCIA" else ACCENT_CYAN)),
                            ft.DataCell(ft.Text(txt_dif_str, weight=ft.FontWeight.BOLD, size=12, color=col_dif)),
                            ft.DataCell(ft.Text(usr_str[:32], size=12, color=UI["texto"])),
                            ft.DataCell(badge_est),
                            ft.DataCell(ft.IconButton(icon=ft.Icons.TASK_ALT_ROUNDED, icon_size=20,
                                                      icon_color=UI["exito"] if est_raw != "CONCILIADO" else UI["texto_3"],
                                                      tooltip="Validar conteo", on_click=validar_ciclico,
                                                      disabled=est_raw == "CONCILIADO")),
                        ]
                    )
                )

            tabla_ciclico_sku.rows = nuevas_filas_cic
            lbl_kpi_cic_total.value = str(len(conteos_ciclico_sku_db))
            lbl_kpi_cic_ok.value = str(cic_conciliados)

            # 2. Construir filas de auditoria_ubicaciones_vacias
            nuevas_filas_vac = []
            hallazgos_vacias = 0

            for row_v in list(conteos_ubic_vacias_db):
                ubi_v = str(
                    row_v.get("codigo_ubicacion")
                    or row_v.get("ubicacion")
                    or row_v.get("posicion")
                    or "-"
                ).strip().upper()
                res_fisico = str(
                    row_v.get("resultado_auditoria")
                    or row_v.get("resultado")
                    or row_v.get("estado_ubicacion")
                    or row_v.get("hallazgo")
                    or ("CONFIRMADA_VACIA" if row_v.get("es_vacia", True) else "OCUPADA_SIN_REGISTRO")
                ).strip().upper()

                es_sin_revisar = ("SIN_REVISAR" in res_fisico or "PEND" in res_fisico)
                es_hallazgo = (
                    "OCUPAD" in res_fisico
                    or "CON STOCK" in res_fisico
                    or "HALLAZGO" in res_fisico
                )
                lpn_raw_v = str(
                    row_v.get("lpn_encontrado")
                    or row_v.get("lpn")
                    or row_v.get("sku_encontrado")
                    or row_v.get("sku")
                    or row_v.get("observacion")
                    or ""
                ).strip().upper()
                if lpn_raw_v and lpn_raw_v not in ("NONE", "NULL", "-", "S/N", "SIN HALLAZGO (VACÍA)"):
                    es_hallazgo = True
                    lpn_hallado = lpn_raw_v
                elif es_hallazgo:
                    lpn_hallado = "ALERTA: OCUPADA SIN REGISTRO"
                elif es_sin_revisar:
                    lpn_hallado = "PENDIENTE DE REVISIÓN"
                else:
                    lpn_hallado = "SIN HALLAZGO (VACÍA)"

                if es_hallazgo:
                    hallazgos_vacias += 1

                usr_raw_v = (
                    row_v.get("auditor")
                    or row_v.get("usuario")
                    or row_v.get("operador")
                    or row_v.get("usuario_rf")
                    or "SIN ASIGNAR"
                )
                usr_str_v = resolver_nombre_usuario(usr_raw_v)
                fecha_v = formatear_fecha_hora(row_v.get("fecha") or row_v.get("created_at") or row_v.get("fecha_auditoria"))
                est_v = str(
                    row_v.get("estado")
                    or ("REVISAR HALLAZGO" if es_hallazgo else ("SIN REVISAR" if es_sin_revisar else "VERIFICADA OK"))
                ).strip().upper()

                if filtro_v and not any(filtro_v in v_str.upper() for v_str in (ubi_v, res_fisico, lpn_hallado, usr_str_v, est_v)):
                    continue

                if es_hallazgo:
                    badge_res = crear_badge_estado("OCUPADA S/REG", "#92400E", "#FEF3C7")
                elif es_sin_revisar:
                    badge_res = crear_badge_estado("SIN REVISAR", "#CBD5E1", "#334155")
                else:
                    badge_res = crear_badge_estado("100% VACÍA", "#065F46", "#D1FAE5")

                badge_est_v = (
                    crear_badge_estado(est_v, "#065F46", "#D1FAE5")
                    if est_v in ("VERIFICADA OK", "AUDITADA", "RESUELTO", "OK", "CONFIRMADA_VACIA")
                    else (
                        crear_badge_estado(est_v, "#1E3A8A", "#DBEAFE")
                        if "SIN REVISAR" in est_v
                        else crear_badge_estado(est_v, "#991B1B", "#FEE2E2")
                    )
                )

                def aprobar_vacia(ev, rv=row_v):
                    rv["estado"] = "VERIFICADA OK"
                    rv["resultado_auditoria"] = "CONFIRMADA_VACIA"
                    if rv.get("id") is not None:
                        for payload_up in ({"estado": "VERIFICADA OK"}, {"resultado_auditoria": "CONFIRMADA_VACIA"}):
                            try:
                                supabase.table("auditoria_ubicaciones_vacias").update(payload_up).eq("id", rv["id"]).execute()
                                break
                            except Exception:
                                continue
                    ubi_notif = rv.get("codigo_ubicacion") or rv.get("ubicacion") or ""
                    notificar(f"Ubicación {ubi_notif} marcada como Verificada OK.", "#047857")
                    renderizar_tablas_auditorias_conteos()

                nuevas_filas_vac.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(fecha_v, size=11, color=UI["texto_2"])),
                            ft.DataCell(ft.Text(ubi_v, weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                            ft.DataCell(badge_res),
                            ft.DataCell(ft.Text(lpn_hallado[:28], weight=ft.FontWeight.BOLD, size=12, color=ACCENT_AMBER if es_hallazgo else TEXT_MUTED)),
                            ft.DataCell(ft.Text(usr_str_v[:24], size=12, color=UI["texto"])),
                            ft.DataCell(badge_est_v),
                            ft.DataCell(ft.IconButton(icon=ft.Icons.DONE_ALL_ROUNDED, icon_size=20,
                                                      icon_color=UI["exito"] if est_v != "VERIFICADA OK" else UI["texto_3"],
                                                      tooltip="Confirmar revisión", on_click=aprobar_vacia,
                                                      disabled=est_v == "VERIFICADA OK")),
                        ]
                    )
                )

            tabla_ubicaciones_vacias.rows = nuevas_filas_vac
            lbl_kpi_vac_total.value = str(len(conteos_ubic_vacias_db))
            lbl_kpi_vac_hallazgo.value = str(hallazgos_vacias)
            page.update()

        txt_buscar_ciclico.on_change = renderizar_tablas_auditorias_conteos
        txt_buscar_vacias.on_change = renderizar_tablas_auditorias_conteos

        def cargar_auditorias_ciclico_y_vacias():
            nonlocal conteos_ubic_vacias_db, conteos_ciclico_sku_db
            bodega_act = obtener_bodega_actual()
            try:
                res_cic = (
                    supabase.table("auditoria_ciclico_sku")
                    .select("*")
                    .eq("bodega", bodega_act)
                    .order("id", desc=True)
                    .limit(250)
                    .execute()
                )
                conteos_ciclico_sku_db = res_cic.data or []
            except Exception:
                try:
                    res_cic = supabase.table("auditoria_ciclico_sku").select("*").order("id", desc=True).limit(250).execute()
                    conteos_ciclico_sku_db = [
                        r for r in (res_cic.data or [])
                        if not r.get("bodega") or str(r.get("bodega")).strip().upper() == bodega_act.upper()
                    ]
                except Exception:
                    conteos_ciclico_sku_db = []

            try:
                res_vac = (
                    supabase.table("auditoria_ubicaciones_vacias")
                    .select("*")
                    .eq("bodega", bodega_act)
                    .order("id", desc=True)
                    .limit(250)
                    .execute()
                )
                conteos_ubic_vacias_db = res_vac.data or []
            except Exception:
                try:
                    res_vac = supabase.table("auditoria_ubicaciones_vacias").select("*").order("id", desc=True).limit(250).execute()
                    conteos_ubic_vacias_db = [
                        r for r in (res_vac.data or [])
                        if not r.get("bodega") or str(r.get("bodega")).strip().upper() == bodega_act.upper()
                    ]
                except Exception:
                    conteos_ubic_vacias_db = []

            renderizar_tablas_auditorias_conteos()

        def dirigir_sku_a_operador(e=None):
            # El SKU dirigido ahora es una tarea de conteo que el operador ve en su celular
            dd_tipo_tarea.value = "SKU"
            asignar_operador_pasillo()

        # --- 10. DESVÍOS, CRUCE ERP Y TRAZABILIDAD (CON FILTRO MULTI-BODEGA) ---
        def renderizar_desvios():
            nuevas_filas_desv = []
            pend, res = 0, 0
            for d in list(desvios_db):
                est = d.get("estado", "PENDIENTE")
                if est == "PENDIENTE":
                    pend += 1
                else:
                    res += 1
                bg_st = "#991B1B" if est == "PENDIENTE" else "#065F46"
                tx_st = "#FEE2E2" if est == "PENDIENTE" else "#D1FAE5"

                u_cod = d.get("usuario") or d.get("operador") or d.get("auditor") or "ADMIN"
                u_nom = resolver_nombre_usuario(u_cod)

                nuevas_filas_desv.append(
                    ft.DataRow(cells=[
                        ft.DataCell(ft.Text(formatear_fecha_hora(d.get("fecha") or d.get("created_at")), weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                        ft.DataCell(ft.Text(d.get("lpn", "-"), weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                        ft.DataCell(ft.Text(d.get("ubicacion_teorica", "-"), weight=ft.FontWeight.BOLD, size=12, color=UI["texto_2"])),
                        ft.DataCell(ft.Text(d.get("incidencia", "-"), weight=ft.FontWeight.BOLD, size=12, color="#F87171")),
                        ft.DataCell(ft.Text(u_nom, size=12, color=UI["texto_2"])),
                        ft.DataCell(crear_badge_estado(est, bg_st, tx_st)),
                        ft.DataCell(ft.IconButton(icon=ft.Icons.TASK_ALT_ROUNDED, icon_size=20, tooltip="Marcar como resuelto",
                                                  icon_color=UI["exito"] if est != "RESUELTO" else UI["texto_3"], disabled=est == "RESUELTO",
                                                  on_click=lambda e, d_r=d: resolver_desvio(d_r))),
                    ])
                )

            tabla_desvios_grua.rows = nuevas_filas_desv
            lbl_dig_desv_pendientes.value = str(pend)
            lbl_dig_desv_resueltos.value = str(res)

        def resolver_desvio(d_r: dict):
            origen, _, id_txt = str(d_r.get("id") or "").partition("-")
            try:
                if origen == "VAC":
                    supabase.table("auditoria_ubicaciones_vacias").update({"estado": "RESUELTO"}).eq("id", int(id_txt)).execute()
                elif origen == "CIC":
                    supabase.table("auditoria_ciclico_sku").update({"estado_auditoria": "CONCILIADO"}).eq("id", int(id_txt)).execute()
            except Exception as ex:
                notificar(f"No se pudo guardar: {ex}", "#B91C1C")
                return
            d_r["estado"] = "RESUELTO"
            renderizar_desvios()
            page.update()

        def cargar_desvios_grua():
            nonlocal desvios_db
            bodega_act = obtener_bodega_actual()
            reales = []

            # 1. Leer alertas en tiempo real de ubicaciones vacías ocupadas desde historial_movimientos filtradas por bodega
            try:
                res_hm = (
                    supabase.table("historial_movimientos")
                    .select("*")
                    .eq("bodega", bodega_act)
                    .eq("tipo_movimiento", "ALERTA_VACIA_OCUPADA")
                    .order("id", desc=True)
                    .limit(50)
                    .execute()
                )
                filas_hm = res_hm.data or []
            except Exception:
                try:
                    res_hm = (
                        supabase.table("historial_movimientos")
                        .select("*")
                        .eq("tipo_movimiento", "ALERTA_VACIA_OCUPADA")
                        .order("id", desc=True)
                        .limit(50)
                        .execute()
                    )
                    filas_hm = [
                        r for r in (res_hm.data or [])
                        if not r.get("bodega") or str(r.get("bodega")).strip().upper() == bodega_act.upper()
                    ]
                except Exception:
                    filas_hm = []

            for hm in filas_hm:
                reales.append({
                    "id": f"HM-{hm.get('id')}",
                    "fecha": hm.get("fecha") or hm.get("created_at"),
                    "lpn": hm.get("lpn") or "SIN-REGISTRO",
                    "ubicacion_teorica": hm.get("ubicacion_destino") or "-",
                    "incidencia": f"ALERTA ROJA RF ({bodega_act}): POSICIÓN VACÍA OCUPADA SIN REGISTRO",
                    "usuario": hm.get("usuario") or "APP_RF",
                    "estado": "PENDIENTE",
                })

            # 2. Sumar hallazgos reales detectados en auditoria_ubicaciones_vacias (ya filtrados por bodega)
            for rv in conteos_ubic_vacias_db:
                res_f = str(rv.get("resultado_auditoria") or rv.get("resultado") or rv.get("estado_ubicacion") or "").upper()
                lpn_h = str(rv.get("lpn_encontrado") or rv.get("lpn") or rv.get("sku_encontrado") or "").strip().upper()
                if "OCUPAD" in res_f or "HALLAZGO" in res_f or (lpn_h and lpn_h not in ("NONE", "NULL", "-", "SIN HALLAZGO (VACÍA)")):
                    reales.append({
                        "id": f"VAC-{rv.get('id')}",
                        "fecha": rv.get("fecha") or rv.get("created_at"),
                        "lpn": lpn_h or "SIN LPN",
                        "ubicacion_teorica": rv.get("codigo_ubicacion") or rv.get("ubicacion") or "-",
                        "incidencia": f"HALLAZGO EN UBICACIÓN VACÍA ({res_f or 'CON STOCK'})",
                        "usuario": rv.get("auditor") or rv.get("usuario") or rv.get("operador") or "AUDITOR",
                        "estado": "RESUELTO" if str(rv.get("estado") or "").upper() in ("VERIFICADA OK", "RESUELTO") else "PENDIENTE",
                    })

            # 3. Sumar incidencias y diferencias reales detectadas en auditoria_ciclico_sku (ya filtrados por bodega)
            for rc in conteos_ciclico_sku_db:
                est_aud = str(rc.get("estado_auditoria") or rc.get("estado") or "").upper()
                c_cont = rc.get("cantidad_contada") if rc.get("cantidad_contada") is not None else rc.get("conteo_fisico")
                c_esp = (
                    rc.get("unidades_sistema")
                    if rc.get("unidades_sistema") is not None
                    else (rc.get("cantidad_esperada") if rc.get("cantidad_esperada") is not None else rc.get("stock_teorico"))
                )
                if est_aud == "INCIDENCIA":
                    reales.append({
                        "id": f"CIC-{rc.get('id')}",
                        "fecha": rc.get("fecha") or rc.get("created_at"),
                        "lpn": f"SKU {rc.get('sku', '-')} ({rc.get('lpn') or 'S/LPN'})",
                        "ubicacion_teorica": rc.get("codigo_ubicacion") or rc.get("ubicacion") or "GENERAL",
                        "incidencia": f"INCIDENCIA CONTEO CÍCLICO SKU (Teórico: {c_esp or 0} UN)",
                        "usuario": rc.get("auditor") or rc.get("usuario") or rc.get("operador") or "AUDITOR",
                        "estado": "PENDIENTE",
                    })
                elif c_cont is not None and c_esp is not None:
                    try:
                        dif_c = int(float(c_cont)) - int(float(c_esp))
                        if dif_c != 0:
                            reales.append({
                                "id": f"CIC-{rc.get('id')}",
                                "fecha": rc.get("fecha") or rc.get("created_at"),
                                "lpn": f"SKU {rc.get('sku', '-')}",
                                "ubicacion_teorica": rc.get("codigo_ubicacion") or rc.get("ubicacion") or "GENERAL",
                                "incidencia": f"DESVÍO CONTEO CÍCLICO ({dif_c:+d} UN)",
                                "usuario": rc.get("auditor") or rc.get("usuario") or rc.get("operador") or "AUDITOR",
                                "estado": "RESUELTO" if est_aud == "CONCILIADO" else "PENDIENTE",
                            })
                    except Exception:
                        pass

            desvios_db = reales
            renderizar_desvios()

        def ejecutar_cruce_erp_wms(e=None):
            sync_stock_inventario()
            bodega_act = obtener_bodega_actual()
            filtro_txt = (txt_buscar_inv.value or "").strip().upper()
            lbl_estado_erp_cruce.value = f"[{bodega_act}] Consultando stock en NetSuite (SuiteQL) y cruzando con Supabase..."
            lbl_estado_erp_cruce.color = ACCENT_CYAN
            page.update()

            stock_erp_map = {}
            if NETSUITE_CONECTADO:
                try:
                    q_ns = """
                        SELECT
                            UPPER(TRIM(i.itemid)) AS sku,
                            SUM(NVL(ib.quantityonhand, 0)) AS stock_erp
                        FROM item i
                        INNER JOIN inventorybalance ib ON i.id = ib.item
                        GROUP BY UPPER(TRIM(i.itemid))
                    """
                    df_ns = consultar_netsuite(q_ns)
                    if df_ns is not None and not df_ns.empty:
                        for _, r_ns in df_ns.iterrows():
                            s_k = str(r_ns.get("sku") or "").strip().upper()
                            if s_k:
                                stock_erp_map[s_k] = int(float(r_ns.get("stock_erp") or 0))
                except Exception as ex_ns:
                    lbl_estado_erp_cruce.value = f"Aviso SuiteQL ({ex_ns}). Mostrando stock físico real de WMS ({bodega_act})."

            todos_skus = sorted(
                set(mapa_stock_por_sku.keys()) | set(stock_erp_map.keys()),
                key=lambda s: (0 if mapa_stock_por_sku.get(s, 0) > 0 else 1, -mapa_stock_por_sku.get(s, 0), s)
            )
            filas_cruce = []
            suma_wms = 0
            suma_erp = 0
            dif_global = 0

            for sku in todos_skus:
                desc_s = mapa_sku_maestra.get(sku, "-")
                if filtro_txt and (filtro_txt not in sku and filtro_txt not in desc_s.upper()):
                    continue

                st_wms = int(mapa_stock_por_sku.get(sku, 0))
                st_erp = int(stock_erp_map.get(sku, st_wms if not stock_erp_map else 0))
                desvio = st_wms - st_erp

                suma_wms += st_wms
                suma_erp += st_erp
                dif_global += abs(desvio)

                if desvio == 0:
                    st_txt, bg_st, tx_st, col_desv = ("CONCILIADO", "#065F46", "#D1FAE5", "#34D399")
                elif desvio > 0:
                    st_txt, bg_st, tx_st, col_desv = ("SOBRANTE EN WMS", "#92400E", "#FEF3C7", "#FBBF24")
                else:
                    st_txt, bg_st, tx_st, col_desv = ("FALTANTE EN WMS", "#991B1B", "#FEE2E2", "#F87171")

                if len(filas_cruce) < 150:
                    filas_cruce.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(sku, weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                                ft.DataCell(ft.Text(desc_s[:35], size=12, color=UI["texto"])),
                                ft.DataCell(ft.Text(f"{st_erp} UN", weight=ft.FontWeight.BOLD, size=12, color=UI["texto_2"])),
                                ft.DataCell(ft.Text(f"{st_wms} UN", weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                                ft.DataCell(ft.Text(f"{desvio:+d} UN", weight=ft.FontWeight.BOLD, size=12, color=col_desv)),
                                ft.DataCell(crear_badge_estado(st_txt, bg_st, tx_st)),
                                ft.DataCell(ft.Row([
                                    ft.IconButton(icon=ft.Icons.SEARCH_ROUNDED, icon_size=18, icon_color=UI["acento"], tooltip="Ver dónde está",
                                                  on_click=lambda ev, s_cod=sku: (self.sel_sub_inventario(0), consultar_stock_sku(s_cod))),
                                    ft.IconButton(icon=ft.Icons.TRACK_CHANGES_ROUNDED, icon_size=18,
                                                  icon_color=UI["alerta"] if desvio != 0 else UI["texto_3"], tooltip="Crear tarea de conteo",
                                                  on_click=lambda ev, s_cod=sku: ir_a_tarea_sku(s_cod)),
                                ], spacing=0, tight=True)),
                            ]
                        )
                    )

            tabla_cruce_erp_wms.rows = filas_cruce
            lbl_kpi_total_wms.value = f"{suma_wms:,}".replace(",", ".")
            lbl_kpi_total_erp.value = f"{suma_erp:,}".replace(",", ".")
            lbl_kpi_dif_global.value = f"{dif_global:,}".replace(",", ".")
            lbl_estado_erp_cruce.value = f"[{bodega_act}] Cruce actualizado: {len(todos_skus)} SKUs analizados | {dif_global} UN con diferencia."
            lbl_estado_erp_cruce.color = "#34D399"
            page.update()

        txt_buscar_inv.on_change = ejecutar_cruce_erp_wms

        def buscar_trazabilidad_lpn(e=None):
            bodega_act = obtener_bodega_actual()
            val = (txt_traz_buscar_lpn.value or "").strip().upper()
            if not val:
                return
            lbl_traz_lpn_actual.value = f"PALLET: {val} ({bodega_act})"
            lbl_traz_lpn_estado.value = "Consultando tablas reales en Supabase..."
            lbl_traz_lpn_estado.color = ACCENT_CYAN
            page.update()

            logs = []

            # 1. Buscar ingreso original en registro_recepcion de la bodega activa
            try:
                res_rec = supabase.table("registro_recepcion").select("*").eq("bodega", bodega_act).ilike("lpn", val).execute()
                for r in (res_rec.data or []):
                    u_rec = r.get("usuario") or r.get("operador") or r.get("recibido_por") or "RECEPCIÓN"
                    logs.append({
                        "fecha": formatear_fecha_hora(r.get("fecha_recepcion") or r.get("created_at") or r.get("fecha")),
                        "evento": f"RECEPCIÓN ANDÉN (SKU: {r.get('sku', '-')} | {r.get('unidades_totales', 0)} UN)",
                        "origen": str(r.get("contenedor") or r.get("codigo_asn") or r.get("numero_oc") or "ANDÉN").upper(),
                        "destino": str(r.get("ubicacion") or "ANDÉN RECEPCIÓN").upper(),
                        "usuario": resolver_nombre_usuario(u_rec),
                        "validacion": "RECEPCIONADO",
                    })
            except Exception:
                pass

            # 2. Buscar posición actual en bodega_inventario_ubicacion de la bodega activa
            try:
                res_ub = supabase.table("bodega_inventario_ubicacion").select("*").eq("bodega", bodega_act).ilike("lpn", val).execute()
                for r in (res_ub.data or []):
                    u_put = r.get("auditor") or r.get("usuario") or r.get("operador") or r.get("ubicado_por") or "OPERADOR RF"
                    unid_rack = r.get("cantidad_unidades") or r.get("unidades") or r.get("cantidad") or 0
                    logs.append({
                        "fecha": formatear_fecha_hora(r.get("fecha") or r.get("updated_at") or r.get("created_at")),
                        "evento": f"ALMACENADO EN RACK ({r.get('sku', '-')} | {unid_rack} UN)",
                        "origen": "RECEPCIÓN / GRÚA",
                        "destino": str(r.get("codigo_ubicacion") or r.get("ubicacion") or "-").upper(),
                        "usuario": resolver_nombre_usuario(u_put),
                        "validacion": "UBICADO EN RACK",
                    })
            except Exception:
                pass

            # 3. Buscar historial en historial_movimientos de la bodega activa
            try:
                res_m = (
                    supabase.table("historial_movimientos")
                    .select("*")
                    .eq("bodega", bodega_act)
                    .ilike("lpn", val)
                    .order("id", desc=False)
                    .execute()
                )
                for r in (res_m.data or []):
                    u_mov = r.get("usuario") or r.get("operador") or r.get("id_usuario") or "OPERADOR RF"
                    logs.append({
                        "fecha": formatear_fecha_hora(r.get("fecha") or r.get("created_at") or r.get("fecha_movimiento")),
                        "evento": str(r.get("tipo_movimiento") or r.get("evento") or r.get("accion") or "MOVIMIENTO RF").upper(),
                        "origen": str(r.get("ubicacion_origen") or r.get("origen") or "-").upper(),
                        "destino": str(r.get("ubicacion_destino") or r.get("destino") or r.get("ubicacion") or "-").upper(),
                        "usuario": resolver_nombre_usuario(u_mov),
                        "validacion": str(r.get("estado") or r.get("resultado") or "CONFIRMADO").upper(),
                    })
            except Exception:
                pass

            if logs:
                lbl_traz_lpn_estado.value = f"UBICACIÓN ACTUAL REGISTRADA ({bodega_act}): {logs[-1]['destino']}"
                lbl_traz_lpn_estado.color = "#34D399"
            else:
                lbl_traz_lpn_estado.value = f"SIN REGISTROS PARA {val} EN {bodega_act.upper()}"
                lbl_traz_lpn_estado.color = "#F87171"

            tabla_trazabilidad_lpn.rows = [
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(l["fecha"], weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(l["evento"], weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(l["origen"], size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(l["destino"], weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(l["usuario"], size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(l["validacion"], weight=ft.FontWeight.BOLD, size=12, color="#34D399")),
                ])
                for l in logs
            ]
            page.update()

        def buscar_trazabilidad_ubic(e=None):
            bodega_act = obtener_bodega_actual()
            val = (txt_traz_buscar_ubic.value or "").strip().upper()
            if not val:
                return
            lbl_traz_ubic_actual.value = f"POSICIÓN RACK: {val} ({bodega_act})"

            logs = []

            # 1. Pallets actualmente ubicados en esa posición en la bodega activa
            try:
                res_u = (
                    supabase.table("bodega_inventario_ubicacion")
                    .select("*")
                    .eq("bodega", bodega_act)
                    .ilike("codigo_ubicacion", val)
                    .execute()
                )
                for r in (res_u.data or []):
                    lpn_r = str(r.get("lpn") or r.get("codigo_lpn") or "").strip().upper()
                    sku_r = str(r.get("sku") or "").strip().upper()
                    if not lpn_r and not sku_r:
                        continue
                    u_cod = r.get("auditor") or r.get("usuario") or r.get("operador") or r.get("ubicado_por") or "OPERADOR RF"
                    unid_u = r.get("cantidad_unidades") or r.get("unidades") or r.get("cantidad") or 0
                    logs.append({
                        "fecha": formatear_fecha_hora(r.get("fecha") or r.get("updated_at") or r.get("created_at")),
                        "lpn": lpn_r or "STOCK EN RACK",
                        "sku_lote": f"{sku_r or '-'} | Lote: {r.get('lote') or 'S/L'} ({unid_u} UN)",
                        "accion": "STOCK ACTUAL EN UBICACIÓN",
                        "usuario": resolver_nombre_usuario(u_cod),
                    })
            except Exception:
                pass

            # 2. Auditorías de ubicaciones vacías realizadas sobre esa ubicación en la bodega activa
            try:
                res_av = (
                    supabase.table("auditoria_ubicaciones_vacias")
                    .select("*")
                    .eq("bodega", bodega_act)
                    .ilike("codigo_ubicacion", val)
                    .order("id", desc=True)
                    .execute()
                )
                for r in (res_av.data or []):
                    u_cod = r.get("auditor") or r.get("usuario") or r.get("operador") or "AUDITOR"
                    hallazgo = r.get("lpn_encontrado") or r.get("sku_encontrado") or r.get("resultado_auditoria") or "VACÍA CONFIRMADA"
                    logs.append({
                        "fecha": formatear_fecha_hora(r.get("fecha") or r.get("created_at")),
                        "lpn": str(hallazgo).upper(),
                        "sku_lote": str(r.get("resultado_auditoria") or r.get("estado") or "AUDITORÍA VACÍAS").upper(),
                        "accion": "AUDITORÍA UBICACIÓN VACÍA",
                        "usuario": resolver_nombre_usuario(u_cod),
                    })
            except Exception:
                pass

            # 3. Conteos cíclicos realizados en esa ubicación en la bodega activa
            try:
                res_ac = (
                    supabase.table("auditoria_ciclico_sku")
                    .select("*")
                    .eq("bodega", bodega_act)
                    .ilike("codigo_ubicacion", val)
                    .order("id", desc=True)
                    .execute()
                )
                for r in (res_ac.data or []):
                    u_cod = r.get("auditor") or r.get("usuario") or r.get("operador") or "AUDITOR"
                    sis_u = r.get("unidades_sistema") if r.get("unidades_sistema") is not None else r.get("cantidad_esperada", 0)
                    est_a = r.get("estado_auditoria") or r.get("cantidad_contada") or "PEND"
                    logs.append({
                        "fecha": formatear_fecha_hora(r.get("fecha") or r.get("created_at")),
                        "lpn": f"SKU {r.get('sku', '-')} ({r.get('lpn') or '-'})",
                        "sku_lote": f"Sist: {sis_u} UN | Resultado: {est_a}",
                        "accion": "CONTEO CÍCLICO SKU DIRIGIDO",
                        "usuario": resolver_nombre_usuario(u_cod),
                    })
            except Exception:
                pass

            # 4. Movimientos históricos desde/hacia esa ubicación en la bodega activa
            for col_m in ("ubicacion_destino", "ubicacion_origen"):
                try:
                    res_m = (
                        supabase.table("historial_movimientos")
                        .select("*")
                        .eq("bodega", bodega_act)
                        .ilike(col_m, val)
                        .order("id", desc=True)
                        .limit(50)
                        .execute()
                    )
                    for r in (res_m.data or []):
                        u_cod = r.get("usuario") or r.get("operador") or "OPERADOR RF"
                        es_ingreso = "destino" in col_m
                        logs.append({
                            "fecha": formatear_fecha_hora(r.get("fecha") or r.get("created_at")),
                            "lpn": str(r.get("lpn") or r.get("codigo_lpn") or "-").upper(),
                            "sku_lote": f"{str(r.get('sku') or 'MOVIMIENTO').upper()} ({r.get('unidades_afectadas') or 0} UN)",
                            "accion": str(r.get("tipo_movimiento") or ("INGRESO A RACK" if es_ingreso else "EXTRACCIÓN DE RACK")).upper(),
                            "usuario": resolver_nombre_usuario(u_cod),
                        })
                except Exception:
                    continue

            lbl_traz_ubic_actual.value = (
                f"POSICIÓN RACK: {val} ({bodega_act} • {len(logs)} registros encontrados)"
                if logs
                else f"POSICIÓN RACK: {val} (Sin registros en {bodega_act})"
            )

            tabla_trazabilidad_ubic.rows = [
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(l["fecha"], weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(l["lpn"], weight=ft.FontWeight.BOLD, size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(l["sku_lote"], size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(l["accion"], weight=ft.FontWeight.BOLD, size=12, color="#34D399" if ("INGRESO" in l["accion"] or "ACTUAL" in l["accion"] or "ALMACENAMIENTO" in l["accion"]) else ACCENT_AMBER)),
                    ft.DataCell(ft.Text(l["usuario"], size=12, color=UI["texto"])),
                ])
                for l in logs
            ]
            page.update()

        txt_traz_buscar_lpn.on_submit = buscar_trazabilidad_lpn
        txt_traz_buscar_ubic.on_submit = buscar_trazabilidad_ubic

        # =====================================================================
        # CONSULTA DE STOCK POR SKU
        # =====================================================================
        mapa_ean_a_sku = {}
        consulta_actual = {"sku": None, "detalle": []}

        txt_consulta_sku = ft.TextField(
            label="SKU, código de barras o descripción",
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            dense=True, text_size=14, autofocus=True,
            color=UI["texto"], bgcolor=UI["input"], border_color=UI["borde"], focused_border_color=UI["acento"],
            label_style=ft.TextStyle(size=12, color=UI["texto_2"]), border_radius=8,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=12),
        )
        fila_sugerencias = ft.Row(spacing=6, wrap=True, run_spacing=6)
        lbl_cons_sku = ft.Text("", size=20, weight=ft.FontWeight.W_700, color=UI["texto"])
        lbl_cons_desc = ft.Text("Busque un producto para ver dónde está y cuánto hay.", size=13, color=UI["texto_2"])
        lbl_cons_meta = ft.Text("", size=12, color=UI["texto_3"])
        lbl_cons_total = ft.Text("—")
        lbl_cons_rack = ft.Text("—")
        lbl_cons_picking = ft.Text("—")
        lbl_cons_comprometido = ft.Text("—")
        lbl_cons_disponible = ft.Text("—")
        lbl_cons_det_total = ft.Text("", size=11, color=UI["texto_3"])
        lbl_cons_det_comp = ft.Text("", size=11, color=UI["texto_3"])
        lbl_cons_det_disp = ft.Text("", size=11, color=UI["texto_3"])
        fila_lotes_consulta = ft.Row(spacing=6, wrap=True, run_spacing=6)

        def tabla_ui(columnas: list):
            return ft.DataTable(
                heading_row_color=UI["card_alt"], heading_row_height=38,
                data_row_min_height=38, data_row_max_height=46,
                column_spacing=22, horizontal_margin=14, divider_thickness=0.5,
                columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in columnas],
                rows=[],
            )

        tabla_consulta_ubic = tabla_ui(["Ubicación", "Zona", "LPN", "Lote", "Vencimiento", "Vence en", "Cajas", "Unidades"])
        tabla_consulta_mov = tabla_ui(["Fecha", "Movimiento", "Desde → hacia", "Unidades", "Usuario"])
        cont_consulta_ubic = ui_tabla(tabla_consulta_ubic, 380)
        cont_consulta_mov = ui_tabla(tabla_consulta_mov, 300)

        def dias_para_vencer(venc: str):
            iso = fecha_a_iso(venc)
            if not iso:
                return None
            try:
                return (datetime.strptime(str(iso)[:10], "%Y-%m-%d").date() - datetime.now().date()).days
            except Exception:
                return None

        def resolver_sku_consulta(texto: str) -> str:
            t = (texto or "").strip().upper()
            if not t:
                return ""
            if t in mapa_sku_maestra:
                return t
            if t in mapa_ean_a_sku:
                return mapa_ean_a_sku[t]
            if t.endswith("-FA") and t[:-3] in mapa_sku_maestra:
                return t[:-3]
            return t

        def sugerir_skus(e=None):
            q = (txt_consulta_sku.value or "").strip().upper()
            fila_sugerencias.controls.clear()
            if len(q) >= 2:
                encontrados = []
                for s, d in mapa_sku_maestra.items():
                    if q in s or q in str(d).upper():
                        encontrados.append(s)
                    if len(encontrados) >= 8:
                        break
                for s in encontrados:
                    fila_sugerencias.controls.append(ft.Container(
                        padding=ft.Padding.symmetric(horizontal=10, vertical=5), border_radius=14,
                        border=ft.Border.all(1, UI["borde"]), ink=True,
                        on_click=lambda ev, sk=s: consultar_stock_sku(sk),
                        content=ft.Text(f"{s} · {str(mapa_sku_maestra.get(s, ''))[:34]}", size=12, color=UI["texto"]),
                    ))
            page.update()

        def consultar_stock_sku(sku_forzado=None):
            if not mapa_sku_maestra:
                sync_stock_inventario()
            sku = resolver_sku_consulta(sku_forzado if isinstance(sku_forzado, str) else txt_consulta_sku.value)
            if not sku:
                return
            txt_consulta_sku.value = sku
            fila_sugerencias.controls.clear()
            bodega_act = obtener_bodega_actual()
            variantes = [sku, f"{sku}-FA"]

            try:
                filas = leer_tabla_paginada(lambda: supabase.table("bodega_inventario_ubicacion").select("*").in_("sku", variantes))
            except Exception as ex:
                notificar(f"No se pudo leer el inventario: {ex}", "#B91C1C")
                return
            filas = [f for f in filas if int(f.get("cantidad_unidades") or 0) > 0]
            en_bodega = [f for f in filas if str(f.get("bodega") or "Bodega Santiago") == bodega_act]
            otra_bodega = sum(int(f.get("cantidad_unidades") or 0) for f in filas if f not in en_bodega)

            comprometido = 0
            ovs_comp = set()
            try:
                det = supabase.table("netsuite_detalle_ov").select("orden_id, cantidad_pedida, cantidad_pickeada").in_("sku", variantes).execute().data or []
                ids = list({d.get("orden_id") for d in det if d.get("orden_id") is not None})
                abiertas = {}
                if ids:
                    for o in leer_por_lista("netsuite_ordenes_venta", "id", ids):
                        est = str(o.get("estado_ns") or o.get("estado") or "").upper()
                        if est in ("", "PENDIENTE", "PENDIENTE_PICKING", "PICKING_EN_PROCESO") and str(o.get("bodega") or "Bodega Santiago") == bodega_act:
                            abiertas[o.get("id")] = o.get("numero_ov")
                for d in det:
                    if d.get("orden_id") in abiertas:
                        pend = max(0, int(d.get("cantidad_pedida") or 0) - int(d.get("cantidad_pickeada") or 0))
                        if pend:
                            comprometido += pend
                            ovs_comp.add(abiertas[d.get("orden_id")])
            except Exception as ex:
                print(f"[WARN] Comprometido SKU: {ex}")

            def zona_de(ubic: str) -> str:
                # Picking = nivel 01 de los racks (H-02-01) o la antigua ZONA-PICKING; ME = mermas de arena
                u = str(ubic or "").upper()
                if u.startswith("ZONA-PICKING") or u == "FARMACIA" or re.match(r"^[A-Z]-\d{2}-01$", u):
                    return "Picking"
                if u.startswith("ZONA-MERMA") or re.match(r"^ME-\d{2}-\d{2}$", u):
                    return "Merma"
                if re.match(r"^(MK|BE)-\d{2}-\d{2}$", u):
                    return "Arena"
                return "Rack"

            total = sum(int(f.get("cantidad_unidades") or 0) for f in en_bodega)
            en_picking = sum(int(f.get("cantidad_unidades") or 0) for f in en_bodega if zona_de(f.get("codigo_ubicacion")) == "Picking")
            en_merma = sum(int(f.get("cantidad_unidades") or 0) for f in en_bodega if zona_de(f.get("codigo_ubicacion")) == "Merma")
            en_rack = total - en_picking - en_merma

            picking_fijo = ""
            try:
                pf = (supabase.table("wms_ubicacion_picking_sku").select("ubicacion").eq("bodega", bodega_act)
                      .in_("sku", variantes).limit(1).execute().data or [])
                picking_fijo = str(pf[0].get("ubicacion") or "").upper() if pf else ""
            except Exception:
                picking_fijo = ""   # sin el script 19 no hay ubicación fija
            disponible = max(0, total - en_merma - comprometido)

            def fmt(n):
                return f"{n:,}".replace(",", ".")

            lbl_cons_sku.value = sku
            lbl_cons_desc.value = str(mapa_sku_maestra.get(sku) or "SKU no registrado en la maestra")
            info_m = mapa_info_maestra.get(sku, {})
            lbl_cons_meta.value = "  ·  ".join(x for x in [
                f"Marca {info_m.get('marca')}" if info_m.get("marca") else "",
                f"EAN {info_m.get('ean')}" if info_m.get("ean") else "",
                f"Caja x{info_m.get('multiplo')}" if info_m.get("multiplo") else "",
                f"Picking fijo {picking_fijo}" if picking_fijo else "Sin ubicación de picking fija",
                bodega_act,
            ] if x)
            lbl_cons_total.value = fmt(total)
            lbl_cons_det_total.value = f"{len({f.get('codigo_ubicacion') for f in en_bodega})} ubicaciones" + (f" · {fmt(otra_bodega)} UN en la otra bodega" if otra_bodega else "")
            lbl_cons_rack.value = fmt(en_rack)
            lbl_cons_picking.value = fmt(en_picking)
            lbl_cons_comprometido.value = fmt(comprometido)
            lbl_cons_det_comp.value = (", ".join(sorted(ovs_comp)[:4]) + (" …" if len(ovs_comp) > 4 else "")) if ovs_comp else "Sin OV abiertas"
            lbl_cons_disponible.value = fmt(disponible)
            lbl_cons_det_disp.value = f"Excluye {fmt(en_merma)} UN en merma" if en_merma else "Stock menos lo comprometido"

            orden = sorted(en_bodega, key=lambda f: (dias_para_vencer(f.get("fecha_vencimiento_cl")) is None,
                                                      dias_para_vencer(f.get("fecha_vencimiento_cl")) or 0,
                                                      str(f.get("codigo_ubicacion") or "")))
            consulta_actual["sku"] = sku
            consulta_actual["detalle"] = orden
            filas_t = []
            por_lote = {}
            for f in orden:
                ubic = str(f.get("codigo_ubicacion") or "-").upper()
                zona = zona_de(ubic)
                if zona == "Picking" and picking_fijo and ubic == picking_fijo:
                    zona = "Picking fijo"
                dias = dias_para_vencer(f.get("fecha_vencimiento_cl"))
                if dias is None:
                    txt_dias, col_dias = "—", UI["texto_3"]
                elif dias < 0:
                    txt_dias, col_dias = "Vencido", UI["peligro"]
                elif dias <= 90:
                    txt_dias, col_dias = f"{dias} días", UI["alerta"]
                else:
                    txt_dias, col_dias = f"{dias // 30} meses", UI["texto_2"]
                lote = str(f.get("lote") or "S/L").upper()
                un = int(f.get("cantidad_unidades") or 0)
                por_lote[lote] = por_lote.get(lote, 0) + un
                filas_t.append(ft.DataRow(cells=[
                    ft.DataCell(ft.Text(ubic, size=12.5, weight=ft.FontWeight.W_700, color=UI["texto"])),
                    ft.DataCell(ft.Text(zona, size=12, weight=ft.FontWeight.W_600 if zona.startswith("Picking") else None,
                                        color=UI["alerta"] if zona == "Merma" else (UI["exito"] if zona.startswith("Picking") else UI["texto_2"]))),
                    ft.DataCell(ft.Text(str(f.get("lpn") or f.get("lpn_origen") or "—"), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(lote, size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(fecha_a_visual(f.get("fecha_vencimiento_cl")) if f.get("fecha_vencimiento_cl") else "S/F", size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(txt_dias, size=12, weight=ft.FontWeight.W_600, color=col_dias)),
                    ft.DataCell(ft.Text(str(int(f.get("cajas") or 0)), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(fmt(un), size=12.5, weight=ft.FontWeight.W_700, color=UI["texto"])),
                ]))
            tabla_consulta_ubic.rows = filas_t
            fila_lotes_consulta.controls = [
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=10, vertical=4), border_radius=12,
                    bgcolor=ft.Colors.with_opacity(0.12, UI["acento"]),
                    content=ft.Text(f"Lote {l}: {fmt(u)} UN", size=12, color=UI["texto"]),
                ) for l, u in sorted(por_lote.items(), key=lambda x: -x[1])
            ]

            try:
                movs = (supabase.table("historial_movimientos").select("*").in_("sku", variantes)
                        .eq("bodega", bodega_act).order("id", desc=True).limit(25).execute().data or [])
            except Exception:
                movs = []
            tabla_consulta_mov.rows = [ft.DataRow(cells=[
                ft.DataCell(ft.Text(formatear_fecha_hora(m.get("fecha")), size=12, color=UI["texto_2"])),
                ft.DataCell(ft.Text(str(m.get("tipo_movimiento") or "-").replace("_", " ").capitalize()[:46], size=12, color=UI["texto"])),
                ft.DataCell(ft.Text(f"{m.get('ubicacion_origen') or '—'} → {m.get('ubicacion_destino') or '—'}", size=12, color=UI["texto_2"])),
                ft.DataCell(ft.Text(f"{int(m.get('unidades_afectadas') or 0):+d}", size=12.5, weight=ft.FontWeight.W_600,
                                    color=UI["exito"] if int(m.get("unidades_afectadas") or 0) >= 0 else UI["peligro"])),
                ft.DataCell(ft.Text(resolver_nombre_usuario(m.get("usuario")), size=12, color=UI["texto_2"])),
            ]) for m in movs]
            bloque_resultado_consulta.visible = True
            txt_vacio_consulta.visible = False
            page.update()

        def exportar_consulta_sku(e=None):
            if not consulta_actual["detalle"]:
                notificar("Primero consulte un SKU.", "#D97706")
                return
            os.makedirs("reportes_inventario", exist_ok=True)
            ruta = os.path.join("reportes_inventario", f"Stock_{consulta_actual['sku']}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
            pd.DataFrame([{
                "SKU": f.get("sku"), "Bodega": f.get("bodega"), "Ubicación": f.get("codigo_ubicacion"), "LPN": f.get("lpn"),
                "Lote": f.get("lote"), "Vencimiento": f.get("fecha_vencimiento_cl"), "Cajas": f.get("cajas"),
                "Unidades": f.get("cantidad_unidades"),
            } for f in consulta_actual["detalle"]]).to_excel(ruta, index=False)
            descargar_o_abrir_archivo(self.page, ruta)

        txt_consulta_sku.on_change = sugerir_skus
        txt_consulta_sku.on_submit = lambda e: consultar_stock_sku()

        # =====================================================================
        # PANTALLAS (una tarea por pantalla)
        # =====================================================================
        def actualizar_todos_los_datos(e=None):
            cargar_usuarios_wms()
            sync_stock_inventario()
            cargar_pasillos_bodega()
            cargar_asignaciones_piso()
            cargar_auditorias_ciclico_y_vacias()
            cargar_desvios_grua()
            if consulta_actual["sku"]:
                consultar_stock_sku(consulta_actual["sku"])
            page.update()

        def ir_a_tarea_sku(sku: str):
            dd_tipo_tarea.value = "SKU"
            txt_sku_dirigido.value = sku
            cambiar_tipo_tarea()
            actualizar_preview_sku_dirigido()
            self.sel_sub_inventario(1)

        txt_vacio_consulta = ft.Container(
            padding=40, alignment=ft.Alignment.CENTER,
            content=ft.Column([
                ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=44, color=UI["texto_3"]),
                ft.Text("Escriba un SKU, escanee un código de barras o busque por descripción.", size=13, color=UI["texto_2"]),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8, tight=True),
        )
        bloque_resultado_consulta = ft.Column([
            ft.Container(
                padding=16, border_radius=10, bgcolor=UI["card"], border=ft.Border.all(1, UI["borde"]),
                content=ft.Row([
                    ft.Column([lbl_cons_sku, lbl_cons_desc, lbl_cons_meta], spacing=2, tight=True, expand=True),
                    ft.Row([
                        ui_boton("Crear tarea de conteo", ft.Icons.TRACK_CHANGES_ROUNDED,
                                 lambda e: ir_a_tarea_sku(consulta_actual["sku"]) if consulta_actual["sku"] else None, "secundario"),
                        ui_boton("Exportar", ft.Icons.DOWNLOAD_ROUNDED, exportar_consulta_sku, "secundario"),
                    ], spacing=8, wrap=True),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ),
            ft.ResponsiveRow([
                ui_kpi(lbl_cons_total, "Stock en bodega", ft.Icons.INVENTORY_2_OUTLINED, UI["acento"], lbl_cons_det_total, col={"xs": 12, "sm": 6, "md": 4, "lg": 3}),
                ui_kpi(lbl_cons_rack, "En reserva y arena", ft.Icons.VIEW_COLUMN_OUTLINED, UI["texto_2"], col={"xs": 12, "sm": 6, "md": 4, "lg": 2}),
                ui_kpi(lbl_cons_picking, "En picking (nivel 01)", ft.Icons.SHOPPING_CART_OUTLINED, UI["texto_2"], col={"xs": 12, "sm": 6, "md": 4, "lg": 2}),
                ui_kpi(lbl_cons_comprometido, "Comprometido en OV", ft.Icons.RECEIPT_LONG_OUTLINED, UI["alerta"], lbl_cons_det_comp, col={"xs": 12, "sm": 6, "md": 6, "lg": 3}),
                ui_kpi(lbl_cons_disponible, "Disponible", ft.Icons.TASK_ALT_ROUNDED, UI["exito"], lbl_cons_det_disp, col={"xs": 12, "sm": 12, "md": 6, "lg": 2}),
            ], spacing=12, run_spacing=12),
            ui_tarjeta(ft.Column([fila_lotes_consulta, cont_consulta_ubic], spacing=10, tight=True),
                       titulo="Dónde está", subtitulo="Ordenado por vencimiento (primero lo que vence antes).", icono=ft.Icons.PLACE_OUTLINED),
            ui_tarjeta(cont_consulta_mov, titulo="Últimos movimientos", icono=ft.Icons.HISTORY_ROUNDED),
        ], spacing=12, visible=False)

        vista_0_consulta = ft.Column([
            ui_tarjeta(ft.Column([txt_consulta_sku, fila_sugerencias], spacing=8, tight=True)),
            txt_vacio_consulta,
            bloque_resultado_consulta,
        ], spacing=12)

        # ---------- Tareas de conteo ----------
        dd_tipo_tarea = dropdown_dark(label="Tipo de tarea", width=200, value="PASILLO",
                                      options=[opt_w(k, v[0]) for k, v in TIPOS_TAREA.items()])
        dd_tipo_tarea.on_select = cambiar_tipo_tarea
        dd_racks_asignacion.label = "Pasillo"
        dd_racks_asignacion.width = 200
        dd_operador_asignar.label = "Operador"
        dd_operador_asignar.width = 260
        txt_sku_dirigido.label = "SKU a contar"
        txt_sku_dirigido.width = 200
        txt_sku_dirigido.visible = False
        txt_Info_sku_dirigido.visible = False
        lbl_aviso_tareas = ft.Text("", size=12, color=UI["alerta"], visible=False)

        vista_1_tareas = ft.Column([
            ui_tarjeta(
                ft.Column([
                    ft.Row([dd_tipo_tarea, dd_racks_asignacion, txt_sku_dirigido, dd_operador_asignar,
                            ui_boton("Asignar tarea", ft.Icons.ASSIGNMENT_IND_ROUNDED, asignar_operador_pasillo)],
                           spacing=10, wrap=True, run_spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    txt_Info_sku_dirigido,
                    ft.Text("Contar pasillo: el operador cuenta cada ubicación con stock del pasillo.  "
                            "Auditar vacías: confirma que las ubicaciones vacías lo estén.  "
                            "Cíclico por SKU: revisa todas las ubicaciones de un producto.",
                            size=11.5, color=UI["texto_3"]),
                ], spacing=10, tight=True),
                titulo="Nueva tarea", icono=ft.Icons.ADD_TASK_ROUNDED,
            ),
            ui_tarjeta(
                ft.Column([lbl_aviso_tareas, cont_asignacion], spacing=8, tight=True),
                titulo="Tareas abiertas y cerradas hoy",
                subtitulo="El avance se calcula solo con lo que el operador registra en el celular.",
                icono=ft.Icons.CHECKLIST_ROUNDED,
            ),
        ], spacing=12)

        # ---------- Resultados de conteo ----------
        txt_buscar_ciclico.expand = None
        txt_buscar_vacias.expand = None
        txt_buscar_ciclico.width = 340
        txt_buscar_vacias.width = 340
        panel_resultado_ciclico = ft.Column([txt_buscar_ciclico, cont_tabla_ciclico], spacing=10)
        panel_resultado_vacias = ft.Column([txt_buscar_vacias, cont_tabla_vacias], spacing=10, visible=False)

        def cambiar_pestana_resultados(i: int):
            panel_resultado_ciclico.visible = i == 0
            panel_resultado_vacias.visible = i == 1
            page.update()

        vista_2_resultados = ft.Column([
            ft.ResponsiveRow([
                ui_kpi(lbl_kpi_cic_total, "Conteos por SKU", ft.Icons.TRACK_CHANGES_ROUNDED, UI["acento"]),
                ui_kpi(lbl_kpi_cic_ok, "Conciliados", ft.Icons.TASK_ALT_ROUNDED, UI["exito"]),
                ui_kpi(lbl_kpi_vac_total, "Vacías auditadas", ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED, UI["texto_2"]),
                ui_kpi(lbl_kpi_vac_hallazgo, "Vacías con stock", ft.Icons.WARNING_AMBER_ROUNDED, UI["alerta"]),
            ], spacing=12, run_spacing=12),
            ui_tarjeta(ft.Column([
                ui_pestanas([("Cíclico por SKU", ft.Icons.TRACK_CHANGES_ROUNDED),
                             ("Ubicaciones vacías", ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED)], cambiar_pestana_resultados),
                panel_resultado_ciclico, panel_resultado_vacias,
            ], spacing=12, tight=True)),
        ], spacing=12)

        # ---------- Conciliación WMS vs NetSuite ----------
        txt_buscar_inv.expand = None
        txt_buscar_inv.width = 320
        vista_3_conciliacion = ft.Column([
            ft.ResponsiveRow([
                ui_kpi(lbl_kpi_total_wms, "Unidades en WMS", ft.Icons.WAREHOUSE_OUTLINED, UI["acento"]),
                ui_kpi(lbl_kpi_total_erp, "Unidades en NetSuite", ft.Icons.CLOUD_OUTLINED, UI["texto_2"]),
                ui_kpi(lbl_kpi_dif_global, "Diferencia absoluta", ft.Icons.COMPARE_ARROWS_ROUNDED, UI["alerta"]),
                ui_kpi(lbl_kpi_avance_audi, "Tareas de conteo abiertas", ft.Icons.CHECKLIST_ROUNDED, UI["exito"]),
            ], spacing=12, run_spacing=12),
            ui_tarjeta(
                ft.Column([lbl_estado_erp_cruce, cont_cruce], spacing=10, tight=True),
                titulo="SKU a SKU", icono=ft.Icons.COMPARE_ARROWS_ROUNDED,
                acciones=[
                    txt_buscar_inv,
                    ui_boton("Cruzar con NetSuite", ft.Icons.SYNC_ALT_ROUNDED, ejecutar_cruce_erp_wms),
                    ui_menu("Exportar", ft.Icons.DOWNLOAD_ROUNDED, [
                        ("Stock WMS por SKU (Excel)", ft.Icons.TABLE_VIEW_ROUNDED, lambda e: (
                            os.makedirs("reportes_inventario", exist_ok=True),
                            pd.DataFrame(datos_stock_wms).to_excel(os.path.join("reportes_inventario", "Stock_WMS.xlsx"), index=False),
                            descargar_o_abrir_archivo(self.page, os.path.join("reportes_inventario", "Stock_WMS.xlsx")),
                        )),
                    ]),
                ],
            ),
        ], spacing=12)

        # ---------- Trazabilidad ----------
        txt_traz_buscar_lpn.width = 360
        txt_traz_buscar_ubic.width = 360
        panel_traz_lpn = ft.Column([
            ft.Row([txt_traz_buscar_lpn, ui_boton("Buscar", ft.Icons.SEARCH_ROUNDED, buscar_trazabilidad_lpn)], spacing=10, wrap=True),
            ft.Row([lbl_traz_lpn_actual, lbl_traz_lpn_estado], spacing=16, wrap=True),
            cont_traz_lpn,
        ], spacing=10)
        panel_traz_ubic = ft.Column([
            ft.Row([txt_traz_buscar_ubic, ui_boton("Buscar", ft.Icons.SEARCH_ROUNDED, buscar_trazabilidad_ubic)], spacing=10, wrap=True),
            lbl_traz_ubic_actual,
            cont_traz_ubic,
        ], spacing=10, visible=False)

        def cambiar_pestana_traz(i: int):
            panel_traz_lpn.visible = i == 0
            panel_traz_ubic.visible = i == 1
            page.update()

        vista_4_trazabilidad = ft.Column([
            ui_tarjeta(ft.Column([
                ui_pestanas([("Por pallet (LPN)", ft.Icons.QR_CODE_2_ROUNDED),
                             ("Por ubicación", ft.Icons.PLACE_OUTLINED)], cambiar_pestana_traz),
                panel_traz_lpn, panel_traz_ubic,
            ], spacing=12, tight=True)),
        ], spacing=12)

        # ---------- Alertas y desvíos ----------
        vista_5_desvios = ft.Column([
            ft.ResponsiveRow([
                ui_kpi(lbl_dig_desv_pendientes, "Pendientes", ft.Icons.WARNING_AMBER_ROUNDED, UI["peligro"], col={"xs": 12, "sm": 6}),
                ui_kpi(lbl_dig_desv_resueltos, "Resueltos", ft.Icons.TASK_ALT_ROUNDED, UI["exito"], col={"xs": 12, "sm": 6}),
            ], spacing=12, run_spacing=12),
            ui_tarjeta(cont_desvios, titulo="Alertas reportadas desde los celulares", icono=ft.Icons.NOTIFICATIONS_ACTIVE_OUTLINED,
                       subtitulo="Ubicaciones vacías con stock y diferencias de conteo cíclico."),
        ], spacing=12)

        # ---------- Armado ----------
        vistas_inv = [vista_0_consulta, vista_1_tareas, vista_2_resultados, vista_3_conciliacion, vista_4_trazabilidad, vista_5_desvios]
        titulos_inv = [
            ("Consulta de stock", "Cuánto hay de un producto y dónde está, con lo comprometido en OV."),
            ("Tareas de conteo", "Asigne pasillos o SKU a un operador; las ve en su celular."),
            ("Resultados de conteo", "Revise y valide lo que contaron los operadores."),
            ("Conciliación WMS vs NetSuite", "Diferencias SKU a SKU entre el stock físico y el ERP."),
            ("Trazabilidad", "Historia completa de un pallet o de una ubicación."),
            ("Alertas y desvíos", "Incidencias reportadas desde los terminales RF."),
        ]
        contenedor_subvista_inv = ft.Container(content=vista_0_consulta)
        lbl_titulo_inv = ft.Text(titulos_inv[0][0], size=18, weight=ft.FontWeight.W_700, color=UI["texto"])
        lbl_sub_inv = ft.Text(titulos_inv[0][1], size=12, color=UI["texto_2"])

        def cambiar_subvista_inv(idx: int):
            nonlocal subvista_activa_idx
            idx = idx if 0 <= idx < len(vistas_inv) else 0
            subvista_activa_idx = idx
            contenedor_subvista_inv.content = vistas_inv[idx]
            lbl_titulo_inv.value, lbl_sub_inv.value = titulos_inv[idx]
            page.update()

        encabezado = ft.Row([
            ft.Row([ft.Icon(ft.Icons.INVENTORY_OUTLINED, size=24, color=UI["acento"]),
                    ft.Column([lbl_titulo_inv, lbl_sub_inv], spacing=1, tight=True)],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ui_boton("Actualizar", ft.Icons.SYNC_ROUNDED, actualizar_todos_los_datos, "secundario"),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True)

        col_principal = ft.Column([encabezado, contenedor_subvista_inv], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)
        self.vista = ft.Container(padding=ft.Padding.only(left=16, top=14, right=16, bottom=16), bgcolor=UI["bg"], content=col_principal, expand=True)
        self.cambiar_subvista_inv_func = cambiar_subvista_inv
        self.actualizar_todos_los_datos_func = actualizar_todos_los_datos

    def cargar_datos_inventario(self, e=None):
        self.actualizar_todos_los_datos_func(e)

    def sel_sub_inventario(self, idx: int):
        # Antes el menú lateral solo recargaba datos y nunca cambiaba de pantalla
        self.cambiar_subvista_inv_func(idx)
