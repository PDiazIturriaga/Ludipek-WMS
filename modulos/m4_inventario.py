import os
import json
import asyncio
import threading
from datetime import datetime
import pandas as pd
import flet as ft
from dependencias import *


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
        lista_usuarios_wms = []       
        mapa_usuarios_wms = {}        
        asignaciones_pasillo_db = []
        conteos_ubic_vacias_db = []   
        conteos_ciclico_sku_db = []   
        desvios_db = []
        subvista_activa_idx = 0

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
            heading_row_color="#181E20", heading_row_height=34, data_row_min_height=32, data_row_max_height=38,
            column_spacing=15, data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("PASILLO", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("USUARIO ASIGNADO (WMS_USUARIOS)", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("FECHA ASIGNACIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("ESTADO CONTEO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        tabla_cruce_erp_wms = ft.DataTable(
            heading_row_color="#181E20", heading_row_height=34, data_row_min_height=32, data_row_max_height=38,
            column_spacing=14, data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("SKU", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("DESCRIPCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("STOCK ERP (NETSUITE)", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("STOCK FÍSICO (WMS)", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("DESVIACIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ESTADO CONCILIACIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIÓN / AJUSTE", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        cont_asignacion = envolver_tabla_scroll(tabla_asignacion_pasillos, 185)
        cont_cruce = envolver_tabla_scroll(tabla_cruce_erp_wms, 310)

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
            heading_row_color="#181E20", heading_row_height=34, data_row_min_height=32, data_row_max_height=38,
            column_spacing=26, data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("FECHA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("SKU DIRIGIDO", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("DESCRIPCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("UBICACIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("TEÓRICO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("CONTEO RF", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("DIF.", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("USUARIO (WMS_USUARIOS)", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ESTADO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        tabla_ubicaciones_vacias = ft.DataTable(
            heading_row_color="#181E20", heading_row_height=34, data_row_min_height=32, data_row_max_height=38,
            column_spacing=36, data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("FECHA / HORA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("UBICACIÓN AUDITADA", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("RESULTADO FÍSICO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("LPN / SKU DETECTADO", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_AMBER)),
                ft.DataColumn(ft.Text("USUARIO (WMS_USUARIOS)", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ESTADO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        cont_tabla_ciclico = envolver_tabla_scroll(tabla_ciclico_sku, 250)
        cont_tabla_vacias = envolver_tabla_scroll(tabla_ubicaciones_vacias, 250)

        # --- 6. CONTROLES ZONA 3: TRAZABILIDAD (LPN HISTORY Y LOGS DE UBICACIÓN) ---
        txt_traz_buscar_lpn = texto_dark("Ingresar o Escanear Código LPN (Ej: LPN-100456)...", width=350, icon=ft.Icons.QR_CODE_2_ROUNDED)
        txt_traz_buscar_ubic = texto_dark("Ingresar Código de Ubicación (Ej: A-01-N2)...", width=350, icon=ft.Icons.LOCATION_ON_OUTLINED)

        lbl_traz_lpn_actual = ft.Text("LPN NO SELECCIONADO", size=15, weight=ft.FontWeight.W_900, color=TEXT_MUTED)
        lbl_traz_lpn_estado = ft.Text("INGRESE UN CÓDIGO", size=12, color=TEXT_MUTED)
        lbl_traz_ubic_actual = ft.Text("UBICACIÓN NO SELECCIONADA", size=15, weight=ft.FontWeight.W_900, color=TEXT_MUTED)

        tabla_trazabilidad_lpn = ft.DataTable(
            heading_row_color="#181E20", heading_row_height=34, data_row_min_height=32, data_row_max_height=38,
            column_spacing=28, data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("FECHA / HORA", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("EVENTO (LPN)", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ZONA ORIGEN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("ZONA DESTINO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("USUARIO RF", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("VALIDACIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        tabla_trazabilidad_ubic = ft.DataTable(
            heading_row_color="#181E20", heading_row_height=34, data_row_min_height=32, data_row_max_height=38,
            column_spacing=28, data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("FECHA / HORA", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("LPN ASOCIADO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("SKU / LOTE", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("ACCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("USUARIO RF", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        cont_traz_lpn = envolver_tabla_scroll(tabla_trazabilidad_lpn, 200)
        cont_traz_ubic = envolver_tabla_scroll(tabla_trazabilidad_ubic, 200)

        # --- 7. CONTROLES ZONA 4: AUDITORÍA EN PISO (DESVÍOS DE GRÚA) ---
        txt_buscar_desvios = texto_dark("Buscar LPN o SKU con desvío...", expand=True, icon=ft.Icons.SEARCH_ROUNDED)

        lbl_dig_desv_pendientes = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color="#F87171", font_family="Consolas")
        lbl_dig_desv_resueltos = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color="#34D399", font_family="Consolas")

        tabla_desvios_grua = ft.DataTable(
            heading_row_color="#181E20", heading_row_height=34, data_row_min_height=32, data_row_max_height=38,
            column_spacing=28, data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("FECHA REPORTE", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("LPN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("UBIC. TEÓRICA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("INCIDENCIA (APP RF)", weight=ft.FontWeight.BOLD, size=10, color="#F87171")),
                ft.DataColumn(ft.Text("REPORTADO POR", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("ESTADO RESOLUCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )
        cont_desvios = envolver_tabla_scroll(tabla_desvios_grua, 320)

        # --- 8. LÓGICA CORE Y SUPABASE (WMS_USUARIOS, ASIGNACIONES Y CONTEOS) ---
        def cargar_usuarios_wms():
            nonlocal lista_usuarios_wms, mapa_usuarios_wms
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
                    if not u_id:
                        continue

                    etiqueta_mostrar = f"{u_id} - {n_comp}" if n_comp.upper() != u_id.upper() else u_id
                    nuevo_mapa[u_id.upper()] = etiqueta_mostrar
                    nuevo_mapa[n_comp.upper()] = etiqueta_mostrar
                    if row.get("id") is not None:
                        nuevo_mapa[str(row.get("id")).upper()] = etiqueta_mostrar

                    if row.get("activo") is False:
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
            nonlocal datos_stock_wms, mapa_sku_maestra, mapa_stock_por_sku, mapa_ubicaciones_por_sku
            nuevo_stock_sku = {}
            nuevas_ubic_sku = {}
            nueva_maestra = {}

            def leer_paginado(nombre_tabla: str, max_reg: int = 4000) -> list:
                acum = []
                paso = 1000
                for off in range(0, max_reg, paso):
                    try:
                        res = supabase.table(nombre_tabla).select("*").range(off, off + paso - 1).execute()
                        lote = res.data or []
                        acum.extend(lote)
                        if len(lote) < paso:
                            break
                    except Exception:
                        break
                return acum

            try:
                # 1. Cargar Maestra de SKUs completa
                for m in leer_paginado("maestra_sku", 4000):
                    s_k = str(m.get("sku") or "").strip().upper()
                    if s_k:
                        nueva_maestra[s_k] = str(m.get("descripcion") or "")

                # 2. Cargar registro_recepcion para cruzar LPNs (SKU y unidades por LPN)
                filas_rec = leer_paginado("registro_recepcion", 4000)
                mapa_rec_lpn = {}
                for r in filas_rec:
                    lpn_k = str(r.get("lpn") or "").strip().upper()
                    if lpn_k:
                        mapa_rec_lpn[lpn_k] = r

                # 3. Leer TODAS las tablas de ubicaciones en Racks (sin que una bloquee a la otra)
                ubicados_vistos = set()
                lpns_en_racks = set()

                for nom_t in ("bodega_inventario_ubicacion","inventario_ubicaciones", "bodega_ubicaciones", "stock_ubicaciones", "ubicaciones_stock"):
                    filas_u = leer_paginado(nom_t, 4000)
                    for r in filas_u:
                        ubi_r = str(r.get("ubicacion") or r.get("codigo_ubicacion") or r.get("posicion") or "").strip().upper()
                        lpn_r = str(r.get("lpn") or r.get("codigo_lpn") or r.get("pallet") or "").strip().upper()
                        sku_r = str(r.get("sku") or "").strip().upper()

                        # Ignorar ubicaciones vacías del maestro de racks
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

                # 4. Incluir también LPNs recepcionados en registro_recepcion (Andén o con ubicación asignada ahí)
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
                datos_stock_wms = [{"sku": k, "unidades": v} for k, v in sorted(nuevo_stock_sku.items())]
                lbl_kpi_total_wms.value = f"{sum(nuevo_stock_sku.values()):,}".replace(",", ".")
            except Exception as ex_s:
                print(f"[WARN] Error consolidando stock WMS: {ex_s}")

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
            ubic_str = ", ".join(ubics[:4]) if ubics else "Sin ubicación registrada"
            if ubics and not (txt_ubic_sku_dirigido.value or "").strip():
                txt_ubic_sku_dirigido.value = ubics[0]
            txt_Info_sku_dirigido.value = f"📦 {sku_in}: {desc}  |  Stock Teórico WMS: {st_teo} UN  |  Ubicaciones: {ubic_str}"
            txt_Info_sku_dirigido.color = ACCENT_CYAN
            page.update()

        txt_sku_dirigido.on_change = actualizar_preview_sku_dirigido

        # --- ASIGNACIONES DE PASILLO VINCULADAS A WMS_USUARIOS ---
        # --- ASIGNACIONES DE PASILLO VINCULADAS A WMS_USUARIOS ---
        def renderizar_asignaciones():
            nuevas_filas_asig = []
            completadas_cnt = 0
            for reg in list(asignaciones_pasillo_db):
                est = str(reg.get("estado") or "EN PROCESO").upper()
                if est in ("COMPLETADA", "COMPLETADO", "CERRADO", "AUDITADO"):
                    completadas_cnt += 1
                bg_est = "#1E3A8A" if est == "EN PROCESO" else "#065F46"
                txt_est = "#DBEAFE" if est == "EN PROCESO" else "#D1FAE5"

                u_raw = (
                    reg.get("usuario")
                    or reg.get("operador")
                    or reg.get("usuario_asignado")
                    or reg.get("nombre_usuario")
                    or "SIN ASIGNAR"
                )
                u_mostrar = resolver_nombre_usuario(u_raw)
                f_str = formatear_fecha_hora(reg.get("fecha") or reg.get("fecha_asignacion") or reg.get("created_at"))
                pasillo_str = str(reg.get("pasillo") or reg.get("rack") or reg.get("zona") or "RACK A").upper()

                def cerrar_pasillo(ev, item_r=reg):
                    item_r["estado"] = "COMPLETADA"
                    id_r = item_r.get("id")
                    if id_r:
                        for t_nom in ("wms_asignaciones_pasillo", "asignaciones_pasillo", "auditoria_pasillos"):
                            try:
                                supabase.table(t_nom).update({"estado": "COMPLETADA"}).eq("id", id_r).execute()
                                break
                            except Exception:
                                continue
                    renderizar_asignaciones()
                    page.update()

                nuevas_filas_asig.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(pasillo_str, weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.PERSON_PIN_ROUNDED, color=ACCENT_CYAN, size=15),
                                        ft.Text(u_mostrar, size=11, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                                    ],
                                    spacing=5,
                                )
                            ),
                            ft.DataCell(ft.Text(f_str, size=11, color=TEXT_MUTED)),
                            ft.DataCell(crear_badge_estado(est, bg_est, txt_est)),
                            ft.DataCell(
                                boton_primario(
                                    "CERRAR CONTEO",
                                    ft.Icons.CHECK_CIRCLE_OUTLINE,
                                    cerrar_pasillo,
                                    "#047857" if est == "EN PROCESO" else "#334155",
                                    height_val=26,
                                )
                            ),
                        ]
                    )
                )

            # Aquí se asignan todas las filas de golpe (justo fuera del ciclo for)
            tabla_asignacion_pasillos.rows = nuevas_filas_asig

            if asignaciones_pasillo_db:
                pct = int(round((completadas_cnt / len(asignaciones_pasillo_db)) * 100))
                lbl_kpi_avance_audi.value = f"{pct}%"
            else:
                lbl_kpi_avance_audi.value = "0%"

        def cargar_asignaciones_piso():
            nonlocal asignaciones_pasillo_db
            cargadas = []
            for nom_t in ("cantidad_unidades","wms_asignaciones_pasillo", "asignaciones_pasillo", "auditoria_pasillos"):
                try:
                    res = supabase.table(nom_t).select("*").order("id", desc=True).limit(100).execute()
                    if res.data is not None:
                        cargadas = res.data
                        break
                except Exception:
                    continue

            if not cargadas and lista_usuarios_wms:
                for u_row in lista_usuarios_wms:
                    pas_u = u_row.get("pasillo_asignado") or u_row.get("pasillo") or u_row.get("rack_asignado")
                    if pas_u and str(pas_u).strip().upper() not in ("NONE", "NULL", ""):
                        cargadas.append({
                            "id": u_row.get("id"),
                            "pasillo": str(pas_u).upper(),
                            "usuario": u_row.get("usuario"),
                            "fecha": u_row.get("updated_at") or u_row.get("created_at"),
                            "estado": u_row.get("estado_auditoria") or "EN PROCESO",
                        })

            asignaciones_pasillo_db = cargadas
            renderizar_asignaciones()

        def asignar_operador_pasillo(e=None):
            p_sel = dd_racks_asignacion.value or "RACK A"
            o_sel = dd_operador_asignar.value
            if not o_sel:
                notificar("Seleccione un usuario válido de wms_usuarios.", "#D97706")
                return

            ahora_iso = datetime.now().strftime("%Y-%m-%d %H:%M")
            guardado_db = False

            for nom_t in ("wms_asignaciones_pasillo", "asignaciones_pasillo", "auditoria_pasillos"):
                if guardado_db:
                    break
                for payload in (
                    {"pasillo": p_sel, "operador": o_sel, "usuario": o_sel, "estado": "EN PROCESO"},
                    {"pasillo": p_sel, "operador": o_sel, "estado": "EN PROCESO"},
                    {"pasillo": p_sel, "usuario": o_sel, "estado": "EN PROCESO"},
                ):
                    try:
                        supabase.table(nom_t).insert(payload).execute()
                        guardado_db = True
                        break
                    except Exception:
                        continue

            try:
                supabase.table("wms_usuarios").update({"pasillo_asignado": p_sel}).eq("usuario", o_sel).execute()
            except Exception:
                pass

            asignaciones_pasillo_db.insert(0, {
                "id": len(asignaciones_pasillo_db) + 1,
                "pasillo": p_sel,
                "usuario": o_sel,
                "operador": o_sel,
                "fecha": ahora_iso,
                "estado": "EN PROCESO",
            })
            notificar(f"{p_sel} asignado a {resolver_nombre_usuario(o_sel)}.", "#047857")
            renderizar_asignaciones()
            page.update()

        # --- 9. LÓGICA ZONA 2: AUDITORÍA CÍCLICA SKU DIRIGIDO & UBICACIONES VACÍAS ---
        def renderizar_tablas_auditorias_conteos(e=None):
            filtro_c = (txt_buscar_ciclico.value or "").strip().upper()
            filtro_v = (txt_buscar_vacias.value or "").strip().upper()

            # 1. Construir filas de auditoria_ciclico_sku (SKU Dirigido)
            nuevas_filas_cic = []
            cic_conciliados = 0

            for row_c in list(conteos_ciclico_sku_db):
                sku_c = str(row_c.get("sku") or row_c.get("codigo_sku") or "-").strip().upper()
                desc_c = str(row_c.get("descripcion") or mapa_sku_maestra.get(sku_c, "Producto en Conteo Cíclico"))
                ubi_c = str(
                    row_c.get("ubicacion")
                    or row_c.get("codigo_ubicacion")
                    or ", ".join(sorted(mapa_ubicaciones_por_sku.get(sku_c, set()))[:2])
                    or "MÚLTIPLES"
                ).strip().upper()

                teo_val = row_c.get("cantidad_esperada")
                if teo_val is None:
                    teo_val = row_c.get("unidades_sistema")
                if teo_val is None:
                    teo_val = row_c.get("stock_teorico")
                if teo_val is None:
                    teo_val = row_c.get("stock_sistema")
                if teo_val is None:
                    teo_val = mapa_stock_por_sku.get(sku_c, 0)
                teo_int = int(teo_val or 0)
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
                cont_int = int(cont_raw) if tiene_conteo else 0
                dif_int = (cont_int - teo_int) if tiene_conteo else 0

                usr_raw = (
                    row_c.get("usuario")
                    or row_c.get("operador")
                    or row_c.get("usuario_asignado")
                    or row_c.get("auditor")
                    or row_c.get("creado_por")
                    or "SIN ASIGNAR"
                )
                usr_str = resolver_nombre_usuario(usr_raw)
                fecha_c = formatear_fecha_hora(row_c.get("created_at") or row_c.get("fecha") or row_c.get("fecha_conteo"))

                est_raw = str(row_c.get("estado") or "").strip().upper()
                if not est_raw:
                    if not tiene_conteo:
                        est_raw = "SKU DIRIGIDO (PEND.)"
                    elif dif_int == 0:
                        est_raw = "CUADRADO OK"
                    else:
                        est_raw = "CON DIFERENCIA"

                if est_raw in ("CUADRADO OK", "CONCILIADO", "APROBADO", "OK", "COMPLETADO"):
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
                    if r_item.get("id") is not None:
                        try:
                            supabase.table("auditoria_ciclico_sku").update({"estado": "CONCILIADO"}).eq("id", r_item["id"]).execute()
                        except Exception:
                            pass
                    notificar(f"Conteo cíclico de SKU {r_item.get('sku', '')} validado.", "#047857")
                    renderizar_tablas_auditorias_conteos()

                txt_dif_str = f"{dif_int:+d} UN" if tiene_conteo else "PEND."
                col_dif = "#34D399" if (tiene_conteo and dif_int == 0) else ("#F87171" if tiene_conteo else TEXT_MUTED)

                nuevas_filas_cic.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(fecha_c, size=10, color=TEXT_MUTED)),
                            ft.DataCell(ft.Text(sku_c, weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(desc_c[:48], size=11, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(ubi_c, weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(f"{teo_int} UN", size=11, color=TEXT_MUTED)),
                            ft.DataCell(ft.Text(f"{cont_int} UN" if tiene_conteo else "En espera RF", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(txt_dif_str, weight=ft.FontWeight.BOLD, size=11, color=col_dif)),
                            ft.DataCell(ft.Text(usr_str[:32], size=11, color=TEXT_WHITE)),
                            ft.DataCell(badge_est),
                            ft.DataCell(
                                boton_primario(
                                    "VALIDAR",
                                    ft.Icons.CHECK_CIRCLE_OUTLINE,
                                    validar_ciclico,
                                    "#047857" if est_raw != "CONCILIADO" else "#334155",
                                    height_val=26,
                                )
                            ),
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
                    row_v.get("ubicacion")
                    or row_v.get("codigo_ubicacion")
                    or row_v.get("posicion")
                    or "-"
                ).strip().upper()
                res_fisico = str(
                row_v.get("resultado_auditoria")
                or row_v.get("resultado")
                or row_v.get("estado_ubicacion")
                or row_v.get("hallazgo")
                or ("VACÍA CONFIRMADA" if row_v.get("es_vacia", True) else "OCUPADA CON STOCK")
                ).strip().upper()
                lpn_hallado = str(
                    row_v.get("lpn_encontrado")
                    or row_v.get("lpn")
                    or row_v.get("sku_encontrado")
                    or row_v.get("sku")
                    or row_v.get("observacion")
                    or "SIN HALLAZGO (VACÍA)"
                ).strip().upper()

                es_hallazgo = (
                    "OCUPAD" in res_fisico
                    or "CON STOCK" in res_fisico
                    or "HALLAZGO" in res_fisico
                    or (lpn_hallado not in ("SIN HALLAZGO (VACÍA)", "NONE", "NULL", "-", "S/N", ""))
                )
                if es_hallazgo:
                    hallazgos_vacias += 1

                usr_raw_v = (
                    row_v.get("usuario")
                    or row_v.get("operador")
                    or row_v.get("auditor")
                    or row_v.get("usuario_rf")
                    or "SIN ASIGNAR"
                )
                usr_str_v = resolver_nombre_usuario(usr_raw_v)
                fecha_v = formatear_fecha_hora(row_v.get("created_at") or row_v.get("fecha") or row_v.get("fecha_auditoria"))
                est_v = str(row_v.get("estado") or ("REVISAR HALLAZGO" if es_hallazgo else "VERIFICADA OK")).strip().upper()

                if filtro_v and not any(filtro_v in v_str.upper() for v_str in (ubi_v, res_fisico, lpn_hallado, usr_str_v, est_v)):
                    continue

                badge_res = (
                    crear_badge_estado("HALLAZGO STOCK", "#92400E", "#FEF3C7")
                    if es_hallazgo
                    else crear_badge_estado("100% VACÍA", "#065F46", "#D1FAE5")
                )
                badge_est_v = (
                    crear_badge_estado(est_v, "#065F46", "#D1FAE5")
                    if est_v in ("VERIFICADA OK", "AUDITADA", "RESUELTO", "OK")
                    else crear_badge_estado(est_v, "#991B1B", "#FEE2E2")
                )

                def aprobar_vacia(ev, rv=row_v):
                    rv["estado"] = "VERIFICADA OK"
                    if rv.get("id") is not None:
                        try:
                            supabase.table("auditoria_ubicaciones_vacias").update({"estado": "VERIFICADA OK"}).eq("id", rv["id"]).execute()
                        except Exception:
                            pass
                    notificar(f"Ubicación {rv.get('ubicacion', '')} marcada como Verificada OK.", "#047857")
                    renderizar_tablas_auditorias_conteos()

                nuevas_filas_vac.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(fecha_v, size=10, color=TEXT_MUTED)),
                            ft.DataCell(ft.Text(ubi_v, weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(badge_res),
                            ft.DataCell(ft.Text(lpn_hallado[:26], weight=ft.FontWeight.BOLD, size=11, color=ACCENT_AMBER if es_hallazgo else TEXT_MUTED)),
                            ft.DataCell(ft.Text(usr_str_v[:24], size=11, color=TEXT_WHITE)),
                            ft.DataCell(badge_est_v),
                            ft.DataCell(
                                boton_primario(
                                    "CONFIRMAR",
                                    ft.Icons.DONE_ALL_ROUNDED,
                                    aprobar_vacia,
                                    "#047857" if est_v != "VERIFICADA OK" else "#334155",
                                    height_val=26,
                                )
                            ),
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
            try:
                res_cic = supabase.table("auditoria_ciclico_sku").select("*").order("id", desc=True).limit(250).execute()
                conteos_ciclico_sku_db = res_cic.data or []
            except Exception:
                try:
                    res_cic = supabase.table("auditoria_ciclico_sku").select("*").limit(250).execute()
                    conteos_ciclico_sku_db = res_cic.data or []
                except Exception:
                    conteos_ciclico_sku_db = []

            try:
                res_vac = supabase.table("auditoria_ubicaciones_vacias").select("*").order("id", desc=True).limit(250).execute()
                conteos_ubic_vacias_db = res_vac.data or []
            except Exception:
                try:
                    res_vac = supabase.table("auditoria_ubicaciones_vacias").select("*").limit(250).execute()
                    conteos_ubic_vacias_db = res_vac.data or []
                except Exception:
                    conteos_ubic_vacias_db = []

            renderizar_tablas_auditorias_conteos()

        def dirigir_sku_a_operador(e=None):
            sku_obj = (txt_sku_dirigido.value or "").strip().upper()
            ubic_obj = (txt_ubic_sku_dirigido.value or "").strip().upper()
            usr_obj = dd_operador_sku_dirigido.value
            if not sku_obj:
                notificar("Ingrese un SKU válido para dirigir el conteo cíclico.", "#D97706")
                return
            if not usr_obj:
                notificar("Seleccione un usuario de wms_usuarios para asignarle el SKU dirigido.", "#D97706")
                return

            st_teo = mapa_stock_por_sku.get(sku_obj, 0)
            desc_s = mapa_sku_maestra.get(sku_obj, "SKU Dirigido")
            if not ubic_obj:
                ubics_s = sorted(mapa_ubicaciones_por_sku.get(sku_obj, set()))
                ubic_obj = ubics_s[0] if ubics_s else "GENERAL"

            esquemas_candidatos = [
                {
                    "sku": sku_obj,
                    "descripcion": desc_s,
                    "ubicacion": ubic_obj,
                    "cantidad_esperada": st_teo,
                    "usuario": usr_obj,
                    "estado": "PENDIENTE",
                },
                {
                    "sku": sku_obj,
                    "ubicacion": ubic_obj,
                    "stock_teorico": st_teo,
                    "usuario": usr_obj,
                    "estado": "PENDIENTE",
                },
                {
                    "sku": sku_obj,
                    "ubicacion": ubic_obj,
                    "operador": usr_obj,
                    "estado": "PENDIENTE",
                },
                {
                    "sku": sku_obj,
                    "usuario": usr_obj,
                },
            ]
            insertado_db = False
            for payload in esquemas_candidatos:
                try:
                    supabase.table("auditoria_ciclico_sku").insert(payload).execute()
                    insertado_db = True
                    break
                except Exception:
                    continue

            if not insertado_db:
                conteos_ciclico_sku_db.insert(0, {
                    "id": len(conteos_ciclico_sku_db) + 1,
                    "sku": sku_obj,
                    "descripcion": desc_s,
                    "ubicacion": ubic_obj,
                    "cantidad_esperada": st_teo,
                    "cantidad_contada": None,
                    "usuario": usr_obj,
                    "estado": "SKU DIRIGIDO (PEND.)",
                    "created_at": datetime.now().isoformat(),
                })
            else:
                cargar_auditorias_ciclico_y_vacias()

            txt_sku_dirigido.value = ""
            txt_ubic_sku_dirigido.value = ""
            notificar(f"SKU Dirigido [{sku_obj}] asignado a {resolver_nombre_usuario(usr_obj)}.", "#047857")
            renderizar_tablas_auditorias_conteos()

        # --- 10. DESVÍOS, CRUCE ERP Y TRAZABILIDAD ---
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

                u_cod = d.get("usuario") or d.get("operador") or "ADMIN"
                u_nom = resolver_nombre_usuario(u_cod)

                nuevas_filas_desv.append(
                    ft.DataRow(cells=[
                        ft.DataCell(ft.Text(formatear_fecha_hora(d.get("fecha") or d.get("created_at")), weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                        ft.DataCell(ft.Text(d.get("lpn", "-"), weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                        ft.DataCell(ft.Text(d.get("ubicacion_teorica", "-"), weight=ft.FontWeight.BOLD, size=11, color=TEXT_MUTED)),
                        ft.DataCell(ft.Text(d.get("incidencia", "-"), weight=ft.FontWeight.BOLD, size=11, color="#F87171")),
                        ft.DataCell(ft.Text(u_nom, size=11, color=TEXT_MUTED)),
                        ft.DataCell(crear_badge_estado(est, bg_st, tx_st)),
                        ft.DataCell(boton_primario("MARCAR RESUELTO", ft.Icons.DONE_ALL_ROUNDED, lambda e, d_r=d: (d_r.update({"estado": "RESUELTO"}), renderizar_desvios(), page.update()), "#047857" if est != "RESUELTO" else "#334155", height_val=26)),
                    ])
                )

            tabla_desvios_grua.rows = nuevas_filas_desv
            lbl_dig_desv_pendientes.value = str(pend)
            lbl_dig_desv_resueltos.value = str(res)

        def cargar_desvios_grua():
            nonlocal desvios_db
            reales = []
            # 1. Leer tabla directa de desvíos si existe
            for nom_t in ("wms_desvios_inventario", "desvios_grua", "reporte_desvios", "incidencias_rf"):
                try:
                    res = supabase.table(nom_t).select("*").order("id", desc=True).limit(100).execute()
                    if res.data:
                        reales.extend(res.data)
                        break
                except Exception:
                    continue

            # 2. Sumar hallazgos reales detectados en auditoria_ubicaciones_vacias
            for rv in conteos_ubic_vacias_db:
                res_f = str(rv.get("resultado") or rv.get("estado_ubicacion") or rv.get("resultado_auditoria") or"").upper()
                lpn_h = str(rv.get("lpn_encontrado") or rv.get("lpn") or rv.get("sku_encontrado") or "").strip().upper()
                if "OCUPAD" in res_f or "HALLAZGO" in res_f or (lpn_h and lpn_h not in ("NONE", "NULL", "-", "SIN HALLAZGO (VACÍA)")):
                    reales.append({
                        "id": f"VAC-{rv.get('id')}",
                        "fecha": rv.get("created_at") or rv.get("fecha"),
                        "lpn": lpn_h or "SIN LPN",
                        "ubicacion_teorica": rv.get("ubicacion") or rv.get("codigo_ubicacion") or "-",
                        "incidencia": f"HALLAZGO EN UBICACIÓN VACÍA ({res_f or 'CON STOCK'})",
                        "usuario": rv.get("usuario") or rv.get("operador") or "AUDITOR",
                        "estado": "RESUELTO" if str(rv.get("estado") or "").upper() in ("VERIFICADA OK", "RESUELTO") else "PENDIENTE",
                    })

            # 3. Sumar diferencias reales detectadas en auditoria_ciclico_sku
            for rc in conteos_ciclico_sku_db:
                c_cont = rc.get("cantidad_contada") if rc.get("cantidad_contada") is not None else rc.get("conteo_fisico")
                c_esp = rc.get("cantidad_esperada") if rc.get("cantidad_esperada") is not None else rc.get("stock_teorico")
                if c_cont is not None and c_esp is not None:
                    try:
                        dif_c = int(c_cont) - int(c_esp)
                        if dif_c != 0:
                            reales.append({
                                "id": f"CIC-{rc.get('id')}",
                                "fecha": rc.get("created_at") or rc.get("fecha"),
                                "lpn": f"SKU {rc.get('sku', '-')}",
                                "ubicacion_teorica": rc.get("ubicacion") or "GENERAL",
                                "incidencia": f"DESVÍO CONTEO CÍCLICO ({dif_c:+d} UN)",
                                "usuario": rc.get("usuario") or rc.get("operador") or "AUDITOR",
                                "estado": "RESUELTO" if str(rc.get("estado") or "").upper() == "CONCILIADO" else "PENDIENTE",
                            })
                    except Exception:
                        pass

            desvios_db = reales
            renderizar_desvios()

        def ejecutar_cruce_erp_wms(e=None):
            sync_stock_inventario()
            filtro_txt = (txt_buscar_inv.value or "").strip().upper()
            lbl_estado_erp_cruce.value = "Consultando stock real en NetSuite (SuiteQL) y cruzando con Supabase..."
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
                    lbl_estado_erp_cruce.value = f"Aviso SuiteQL ({ex_ns}). Mostrando stock físico real de WMS."

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
                                ft.DataCell(ft.Text(sku, weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(desc_s[:35], size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"{st_erp} UN", weight=ft.FontWeight.BOLD, size=11, color=TEXT_MUTED)),
                                ft.DataCell(ft.Text(f"{st_wms} UN", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(f"{desvio:+d} UN", weight=ft.FontWeight.BOLD, size=11, color=col_desv)),
                                ft.DataCell(crear_badge_estado(st_txt, bg_st, tx_st)),
                                ft.DataCell(
                                    boton_primario(
                                        "DIRIGIR CONTEO",
                                        ft.Icons.TRACK_CHANGES_ROUNDED,
                                        lambda ev, s_cod=sku: (
                                            setattr(txt_sku_dirigido, "value", s_cod),
                                            actualizar_preview_sku_dirigido(),
                                            cambiar_subvista_inv(1),
                                        ),
                                        ACCENT_AMBER if desvio != 0 else "#334155",
                                        height_val=26,
                                    )
                                ),
                            ]
                        )
                    )

            tabla_cruce_erp_wms.rows = filas_cruce
            lbl_kpi_total_wms.value = f"{suma_wms:,}".replace(",", ".")
            lbl_kpi_total_erp.value = f"{suma_erp:,}".replace(",", ".")
            lbl_kpi_dif_global.value = f"{dif_global:,}".replace(",", ".")
            lbl_estado_erp_cruce.value = f"Cruce real actualizado: {len(todos_skus)} SKUs analizados | {dif_global} UN con diferencia."
            lbl_estado_erp_cruce.color = "#34D399"
            page.update()

        txt_buscar_inv.on_change = ejecutar_cruce_erp_wms

        def buscar_trazabilidad_lpn(e=None):
            val = (txt_traz_buscar_lpn.value or "").strip().upper()
            if not val:
                return
            lbl_traz_lpn_actual.value = f"PALLET: {val}"
            lbl_traz_lpn_estado.value = "Consultando tablas reales en Supabase..."
            lbl_traz_lpn_estado.color = ACCENT_CYAN
            page.update()

            logs = []

            # 1. Buscar ingreso original en registro_recepcion
            try:
                res_rec = supabase.table("registro_recepcion").select("*").ilike("lpn", val).execute()
                for r in (res_rec.data or []):
                    u_rec = r.get("usuario") or r.get("operador") or r.get("recibido_por") or "RECEPCIÓN"
                    logs.append({
                        "fecha": formatear_fecha_hora(r.get("created_at") or r.get("fecha_recepcion") or r.get("fecha")),
                        "evento": f"RECEPCIÓN ANDÉN (SKU: {r.get('sku', '-')} | {r.get('unidades_totales', 0)} UN)",
                        "origen": str(r.get("codigo_asn") or r.get("numero_oc") or "ANDÉN").upper(),
                        "destino": str(r.get("ubicacion") or "ANDÉN RECEPCIÓN").upper(),
                        "usuario": resolver_nombre_usuario(u_rec),
                        "validacion": "RECEPCIONADO",
                    })
            except Exception:
                pass

            # 2. Buscar posición actual en bodega_ubicaciones / inventario_ubicaciones
            for nom_tu in ("cantidad_unidades","bodega_inventario_ubicacion","bodega_ubicaciones", "inventario_ubicaciones"):
                try:
                    res_ub = supabase.table(nom_tu).select("*").ilike("lpn", val).execute()
                    for r in (res_ub.data or []):
                        u_put = r.get("usuario") or r.get("operador") or r.get("ubicado_por") or "OPERADOR RF"
                        logs.append({
                            "fecha": formatear_fecha_hora(r.get("updated_at") or r.get("created_at") or r.get("fecha")),
                            "evento": f"ALMACENADO EN RACK ({r.get('sku', '-')} | {r.get('unidades') or r.get('cantidad') or 0} UN)",
                            "origen": "RECEPCIÓN / GRÚA",
                            "destino": str(r.get("ubicacion") or r.get("codigo_ubicacion") or "-").upper(),
                            "usuario": resolver_nombre_usuario(u_put),
                            "validacion": "UBICADO EN RACK",
                        })
                except Exception:
                    continue

            # 3. Buscar historial en tablas de movimientos
            for nom_tm in ("wms_movimientos", "registro_movimientos", "movimientos", "historial_movimientos"):
                for col_lpn in ("lpn", "codigo_lpn"):
                    try:
                        res_m = supabase.table(nom_tm).select("*").ilike(col_lpn, val).order("id", desc=False).execute()
                        for r in (res_m.data or []):
                            u_mov = r.get("usuario") or r.get("operador") or r.get("id_usuario") or "OPERADOR RF"
                            logs.append({
                                "fecha": formatear_fecha_hora(r.get("created_at") or r.get("fecha_movimiento") or r.get("fecha")),
                                "evento": str(r.get("evento") or r.get("tipo_movimiento") or r.get("accion") or "MOVIMIENTO RF").upper(),
                                "origen": str(r.get("origen") or r.get("ubicacion_origen") or "-").upper(),
                                "destino": str(r.get("destino") or r.get("ubicacion_destino") or r.get("ubicacion") or "-").upper(),
                                "usuario": resolver_nombre_usuario(u_mov),
                                "validacion": str(r.get("estado") or r.get("resultado") or "CONFIRMADO").upper(),
                            })
                        if res_m.data:
                            break
                    except Exception:
                        continue

            if logs:
                lbl_traz_lpn_estado.value = f"UBICACIÓN ACTUAL REGISTRADA: {logs[-1]['destino']}"
                lbl_traz_lpn_estado.color = "#34D399"
            else:
                lbl_traz_lpn_estado.value = f"SIN REGISTROS PARA {val} EN SUPABASE"
                lbl_traz_lpn_estado.color = "#F87171"

            tabla_trazabilidad_lpn.rows = [
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(l["fecha"], weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                    ft.DataCell(ft.Text(l["evento"], weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                    ft.DataCell(ft.Text(l["origen"], size=11, color=TEXT_MUTED)),
                    ft.DataCell(ft.Text(l["destino"], weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                    ft.DataCell(ft.Text(l["usuario"], size=11, color=TEXT_WHITE)),
                    ft.DataCell(ft.Text(l["validacion"], weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                ])
                for l in logs
            ]
            page.update()

        def buscar_trazabilidad_ubic(e=None):
            val = (txt_traz_buscar_ubic.value or "").strip().upper()
            if not val:
                return
            lbl_traz_ubic_actual.value = f"POSICIÓN RACK: {val}"

            logs = []

            # 1. Pallets actualmente ubicados en esa posición (bodega_ubicaciones / inventario_ubicaciones)
            for nom_tu in ("bodega_inventario_ubicacion","bodega_ubicaciones", "inventario_ubicaciones"):
                for col_u in ("ubicacion", "codigo_ubicacion"):
                    try:
                        res_u = supabase.table(nom_tu).select("*").ilike(col_u, val).execute()
                        for r in (res_u.data or []):
                            lpn_r = str(r.get("lpn") or r.get("codigo_lpn") or "").strip().upper()
                            sku_r = str(r.get("sku") or "").strip().upper()
                            if not lpn_r and not sku_r:
                                continue
                            u_cod = r.get("usuario") or r.get("operador") or r.get("ubicado_por") or "OPERADOR RF"
                            logs.append({
                                "fecha": formatear_fecha_hora(r.get("updated_at") or r.get("created_at") or r.get("fecha")),
                                "lpn": lpn_r or "STOCK EN RACK",
                                "sku_lote": f"{sku_r or '-'} | Lote: {r.get('lote') or 'S/L'} ({r.get('unidades') or r.get('cantidad') or 0} UN)",
                                "accion": "STOCK ACTUAL EN UBICACIÓN",
                                "usuario": resolver_nombre_usuario(u_cod),
                            })
                        if res_u.data:
                            break
                    except Exception:
                        continue

            # 2. Auditorías de ubicaciones vacías realizadas sobre esa ubicación
            try:
                res_av = supabase.table("auditoria_ubicaciones_vacias").select("*").ilike("ubicacion", val).order("id", desc=True).execute()
                for r in (res_av.data or []):
                    u_cod = r.get("usuario") or r.get("operador") or r.get("auditor") or "AUDITOR"
                    hallazgo = r.get("lpn_encontrado") or r.get("sku_encontrado") or "VACÍA CONFIRMADA"
                    logs.append({
                        "fecha": formatear_fecha_hora(r.get("created_at") or r.get("fecha")),
                        "lpn": str(hallazgo).upper(),
                        "sku_lote": str(r.get("estado") or r.get("resultado") or "AUDITORÍA VACÍAS").upper(),
                        "accion": "AUDITORÍA UBICACIÓN VACÍA",
                        "usuario": resolver_nombre_usuario(u_cod),
                    })
            except Exception:
                pass

            # 3. Conteos cíclicos realizados en esa ubicación
            try:
                res_ac = supabase.table("auditoria_ciclico_sku").select("*").ilike("ubicacion", val).order("id", desc=True).execute()
                for r in (res_ac.data or []):
                    u_cod = r.get("usuario") or r.get("operador") or r.get("auditor") or "AUDITOR"
                    logs.append({
                        "fecha": formatear_fecha_hora(r.get("created_at") or r.get("fecha")),
                        "lpn": f"SKU {r.get('sku', '-')}",
                        "sku_lote": f"Teórico: {r.get('cantidad_esperada', 0)} | Contado: {r.get('cantidad_contada', 'PEND')}",
                        "accion": "CONTEO CÍCLICO SKU DIRIGIDO",
                        "usuario": resolver_nombre_usuario(u_cod),
                    })
            except Exception:
                pass

            # 4. Movimientos históricos desde/hacia esa ubicación
            for nom_tm in ("wms_movimientos", "registro_movimientos", "movimientos", "historial_movimientos"):
                for col_m in ("destino", "ubicacion_destino", "origen", "ubicacion_origen"):
                    try:
                        res_m = supabase.table(nom_tm).select("*").ilike(col_m, val).order("id", desc=True).limit(50).execute()
                        for r in (res_m.data or []):
                            u_cod = r.get("usuario") or r.get("operador") or "OPERADOR RF"
                            es_ingreso = "destino" in col_m
                            logs.append({
                                "fecha": formatear_fecha_hora(r.get("created_at") or r.get("fecha")),
                                "lpn": str(r.get("lpn") or r.get("codigo_lpn") or "-").upper(),
                                "sku_lote": str(r.get("sku") or "MOVIMIENTO PALLET").upper(),
                                "accion": "INGRESO A RACK" if es_ingreso else "EXTRACCIÓN DE RACK",
                                "usuario": resolver_nombre_usuario(u_cod),
                            })
                    except Exception:
                        continue

            lbl_traz_ubic_actual.value = (
                f"POSICIÓN RACK: {val} ({len(logs)} registros reales encontrados)"
                if logs
                else f"POSICIÓN RACK: {val} (Sin registros en Supabase)"
            )

            tabla_trazabilidad_ubic.rows = [
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(l["fecha"], weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                    ft.DataCell(ft.Text(l["lpn"], weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                    ft.DataCell(ft.Text(l["sku_lote"], size=11, color=TEXT_MUTED)),
                    ft.DataCell(ft.Text(l["accion"], weight=ft.FontWeight.BOLD, size=11, color="#34D399" if ("INGRESO" in l["accion"] or "ACTUAL" in l["accion"]) else ACCENT_AMBER)),
                    ft.DataCell(ft.Text(l["usuario"], size=11, color=TEXT_WHITE)),
                ])
                for l in logs
            ]
            page.update()

        txt_traz_buscar_lpn.on_submit = buscar_trazabilidad_lpn
        txt_traz_buscar_ubic.on_submit = buscar_trazabilidad_ubic

        def actualizar_todos_los_datos():
            cargar_usuarios_wms()
            sync_stock_inventario()
            cargar_asignaciones_piso()
            cargar_auditorias_ciclico_y_vacias()
            cargar_desvios_grua()
            page.update()

        # --- 11. COMPOSICIÓN DE VISTAS FINALES ---

        # ZONA 1: CONTROL Y CONCILIACIÓN (PASILLOS + CRUCE ERP)
        vista_1_control = ft.Column([
            ft.Row([
                tarjeta_dark(ft.Column([
                    ft.Text("ASIGNACIÓN DE PASILLOS Y CONTEO POR USUARIO (WMS_USUARIOS)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Text("Seleccione un pasillo y asígnelo a un usuario activo de la tabla wms_usuarios para su conteo en RF.", size=11, color=TEXT_MUTED),
                    ft.Divider(color=BORDER_COLOR, height=4),
                    ft.Row([dd_racks_asignacion, dd_operador_asignar, boton_primario("ASIGNAR PASILLO", ft.Icons.ASSIGNMENT_IND_ROUNDED, asignar_operador_pasillo, ACCENT_BLUE, height_val=34)], spacing=10, wrap=True),
                    cont_asignacion,
                ], spacing=6), expand_val=True),

                tarjeta_dark(ft.Column([
                    ft.Text("KPI GLOBALES INVENTARIO (WMS vs ERP)", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Row([
                        crear_caja_digital(lbl_kpi_total_wms, "Total WMS (Piso)", ACCENT_CYAN, 90, "Suma total de unidades físicas en Bodega"),
                        crear_caja_digital(lbl_kpi_total_erp, "Total NetSuite", "#10B981", 90, "Suma total de unidades a nivel sistema ERP"),
                        crear_caja_digital(lbl_kpi_dif_global, "Desviación Global", ACCENT_AMBER, 90, "Diferencia absoluta total detectada"),
                        crear_caja_digital(lbl_kpi_avance_audi, "Avance Pasillos", ACCENT_PURPLE, 90, "Porcentaje de pasillos completados"),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ], spacing=8), width_val=420),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START),

            tarjeta_dark(ft.Column([
                ft.Row([
                    ft.Column([
                        ft.Text("CONCILIACIÓN 3-WAY MATCH (SKU A SKU) Y GENERACIÓN DE AJUSTES", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                        lbl_estado_erp_cruce,
                    ], spacing=2),
                    ft.Row([
                        txt_buscar_inv,
                        boton_primario("EJECUTAR CRUCE EN VIVO", ft.Icons.COMPARE_ARROWS_ROUNDED, ejecutar_cruce_erp_wms, ACCENT_TEAL, height_val=30),
                        boton_primario(
    "EXPORTAR EXCEL",
    ft.Icons.TABLE_VIEW_ROUNDED,
    lambda e: (
        os.makedirs("reportes_inventario", exist_ok=True),
        pd.DataFrame(datos_stock_wms).to_excel(os.path.join("reportes_inventario", "Stock_WMS.xlsx"), index=False),
        descargar_o_abrir_archivo(self.page, os.path.join("reportes_inventario", "Stock_WMS.xlsx")),
        notificar("Excel descargado en tu navegador.", "#047857"),
    ),
    ACCENT_BLUE,
    height_val=30,
)
                    ], spacing=8, expand=True, alignment=ft.MainAxisAlignment.END),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(color=BORDER_COLOR, height=1),
                cont_cruce,
            ], spacing=8)),
        ], spacing=10)

        # ZONA 2: CONTEOS CÍCLICOS (AUDITORIA_CICLICO_SKU DIRIGIDO & AUDITORIA_UBICACIONES_VACIAS) - APILADAS
        vista_2_conteos_ciclicos = ft.Column([
            ft.Row([
                tarjeta_dark(ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.TRACK_CHANGES_ROUNDED, color=ACCENT_CYAN, size=18),
                        ft.Text("PROGRAMAR CONTEO CÍCLICO POR SKU DIRIGIDO (TABLA: auditoria_ciclico_sku)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ], spacing=6),
                    txt_Info_sku_dirigido,
                    ft.Divider(color=BORDER_COLOR, height=4),
                    ft.Row([
                        txt_sku_dirigido,
                        txt_ubic_sku_dirigido,
                        dd_operador_sku_dirigido,
                        boton_primario("ENVIAR SKU DIRIGIDO A RF", ft.Icons.SEND_ROUNDED, dirigir_sku_a_operador, ACCENT_BLUE, height_val=34),
                        boton_primario("REFRESCAR CONTEOS", ft.Icons.REFRESH_ROUNDED, lambda e: cargar_auditorias_ciclico_y_vacias(), ACCENT_TEAL, height_val=34),
                    ], spacing=10, wrap=True),
                ], spacing=6), expand_val=True),

                tarjeta_dark(ft.Column([
                    ft.Text("INDICADORES DE AUDITORÍA CÍCLICA Y VACÍAS", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Row([
                        crear_caja_digital(lbl_kpi_cic_total, "SKUs Dirigidos", ACCENT_CYAN, 90, "Total de conteos en auditoria_ciclico_sku"),
                        crear_caja_digital(lbl_kpi_cic_ok, "SKUs Conciliados", ACCENT_GREEN, 90, "Conteos cíclicos cuadrados / validados"),
                        crear_caja_digital(lbl_kpi_vac_total, "Ubic. Vacías Aud.", ACCENT_PURPLE, 90, "Total registros en auditoria_ubicaciones_vacias"),
                        crear_caja_digital(lbl_kpi_vac_hallazgo, "Con Hallazgo", ACCENT_AMBER, 90, "Ubicaciones teóricamente vacías donde se detectó stock"),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ], spacing=8), width_val=420),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START),

            # TABLA 1 ARRIBA (100% ANCHO)
            tarjeta_dark(ft.Column([
                ft.Row([
                    ft.Row([
                        ft.Icon(ft.Icons.FACT_CHECK_OUTLINED if hasattr(ft.Icons, "FACT_CHECK_OUTLINED") else ft.Icons.FACT_CHECK, color=ACCENT_CYAN, size=18),
                        ft.Text("1. RECEPCIÓN DE CONTEOS: SKU DIRIGIDO (auditoria_ciclico_sku)", size=12, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
                    ], spacing=6),
                    txt_buscar_ciclico,
                ], spacing=14, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(color=BORDER_COLOR, height=1),
                cont_tabla_ciclico,
            ], spacing=8)),

            # TABLA 2 ABAJO (100% ANCHO)
            tarjeta_dark(ft.Column([
                ft.Row([
                    ft.Row([
                        ft.Icon(ft.Icons.GRID_OFF_ROUNDED, color=ACCENT_PURPLE, size=18),
                        ft.Text("2. RECEPCIÓN DE CONTEOS: UBICACIONES VACÍAS (auditoria_ubicaciones_vacias)", size=12, weight=ft.FontWeight.BOLD, color=ACCENT_PURPLE),
                    ], spacing=6),
                    txt_buscar_vacias,
                ], spacing=14, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(color=BORDER_COLOR, height=1),
                cont_tabla_vacias,
            ], spacing=8)),
        ], spacing=10)

        # ZONA 3: TRAZABILIDAD (LPN HISTORY & LOGS UBICACIONES) - APILADAS VERTICALMENTE
        vista_3_trazabilidad = ft.Column([
            tarjeta_dark(ft.Column([
                ft.Text("TRAZABILIDAD TRANSVERSAL DE PALLET (LPN HISTORY)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                ft.Text("Visualiza el ciclo de vida completo de un pallet, sus movimientos, validaciones y operadores involucrados.", size=11, color=TEXT_MUTED),
                ft.Divider(color=BORDER_COLOR, height=4),
                ft.Row([txt_traz_buscar_lpn, boton_primario("BUSCAR LPN", ft.Icons.SEARCH_ROUNDED, buscar_trazabilidad_lpn, ACCENT_CYAN, height_val=34)], spacing=10),
                ft.Container(
                    padding=10, bgcolor="#141A1C", border_radius=6, border=ft.Border.all(1, BORDER_COLOR),
                    content=ft.Row([lbl_traz_lpn_actual, lbl_traz_lpn_estado], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ),
                cont_traz_lpn,
            ], spacing=8)),

            tarjeta_dark(ft.Column([
                ft.Text("HISTÓRICO DE MOVIMIENTOS POR UBICACIÓN EN RACK", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                ft.Text("Conoce exactamente quiénes, qué LPNs y cuándo fueron extraídos o ingresados a una posición de rack específica.", size=11, color=TEXT_MUTED),
                ft.Divider(color=BORDER_COLOR, height=4),
                ft.Row([txt_traz_buscar_ubic, boton_primario("BUSCAR UBICACIÓN", ft.Icons.SEARCH_ROUNDED, buscar_trazabilidad_ubic, ACCENT_PURPLE, height_val=34)], spacing=10),
                ft.Container(
                    padding=10, bgcolor="#141A1C", border_radius=6, border=ft.Border.all(1, BORDER_COLOR),
                    content=ft.Row([lbl_traz_ubic_actual], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ),
                cont_traz_ubic,
            ], spacing=8)),
        ], spacing=10)

        # ZONA 4: AUDITORÍA EN PISO (DESVÍOS)
        vista_4_desvios = ft.Column([
            ft.Row([
                tarjeta_dark(ft.Column([
                    ft.Text("AUDITORÍA DE PISO: ALERTAS Y DESVÍOS REPORTADOS POR GRÚEROS (APP RF)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Text("Monitorea incidencias en tiempo real reportadas desde las terminales RF (Ej: Posiciones físicamente ocupadas, Quiebres visuales, LPNs extraviados).", size=11, color=TEXT_MUTED),
                    ft.Divider(color=BORDER_COLOR, height=4),
                    ft.Row([txt_buscar_desvios, boton_primario("ACTUALIZAR", ft.Icons.REFRESH_ROUNDED, lambda e: cargar_desvios_grua(), ACCENT_TEAL, height_val=30)], spacing=10),
                ], spacing=6), expand_val=True),

                tarjeta_dark(ft.Row([
                    crear_caja_digital(lbl_dig_desv_pendientes, "Desvíos Críticos Pendientes", "#EF4444", 160),
                    crear_caja_digital(lbl_dig_desv_resueltos, "Incidencias Resueltas", "#10B981", 160),
                ], spacing=15, alignment=ft.MainAxisAlignment.CENTER), width_val=380),
            ], spacing=10),

            tarjeta_dark(ft.Column([cont_desvios], spacing=0)),
        ], spacing=10)

        # --- 12. BARRA DE NAVEGACIÓN Y ARMADO FINAL ---
        contenedor_subvista_inv = ft.Container(content=vista_1_control)

        btn_modo_control = ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=7), bgcolor=ACCENT_TEAL, border_radius=6, border=ft.Border.all(1, ACCENT_CYAN), ink=True,
            content=ft.Row([ft.Icon(ft.Icons.RULE_ROUNDED, color=TEXT_WHITE, size=16), ft.Text("1. PASILLOS Y CRUCE ERP", size=11, weight=ft.FontWeight.BOLD, color=TEXT_WHITE)], spacing=6, tight=True),
        )
        btn_modo_ciclico = ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=7), bgcolor="#181E20", border_radius=6, border=ft.Border.all(1, BORDER_COLOR), ink=True,
            content=ft.Row([ft.Icon(ft.Icons.TRACK_CHANGES_ROUNDED, color=ACCENT_GREEN, size=16), ft.Text("2. SKU DIRIGIDO & UBIC. VACÍAS", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED)], spacing=6, tight=True),
        )
        btn_modo_traz = ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=7), bgcolor="#181E20", border_radius=6, border=ft.Border.all(1, BORDER_COLOR), ink=True,
            content=ft.Row([ft.Icon(ft.Icons.HISTORY_ROUNDED, color=ACCENT_CYAN, size=16), ft.Text("3. TRAZABILIDAD LPN / RACK", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED)], spacing=6, tight=True),
        )
        btn_modo_desv = ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=7), bgcolor="#181E20", border_radius=6, border=ft.Border.all(1, BORDER_COLOR), ink=True,
            content=ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ACCENT_AMBER, size=16), ft.Text("4. ALERTAS Y DESVÍOS (RF)", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED)], spacing=6, tight=True),
        )

        def cambiar_subvista_inv(idx: int):
            nonlocal subvista_activa_idx
            if idx not in (0, 1, 2, 3):
                idx = 0
            subvista_activa_idx = idx
            contenedor_subvista_inv.content = [
                vista_1_control,
                vista_2_conteos_ciclicos,
                vista_3_trazabilidad,
                vista_4_desvios,
            ][idx]

            pares_botones = [
                (0, btn_modo_control),
                (1, btn_modo_ciclico),
                (2, btn_modo_traz),
                (3, btn_modo_desv),
            ]
            for i_b, b_ctrl in pares_botones:
                activo = i_b == idx
                b_ctrl.bgcolor = ACCENT_TEAL if activo else "#181E20"
                b_ctrl.border = ft.Border.all(1.5 if activo else 1, ACCENT_CYAN if activo else BORDER_COLOR)
                b_ctrl.content.controls[1].color = TEXT_WHITE if activo else TEXT_MUTED
            page.update()

        btn_modo_control.on_click = lambda e: cambiar_subvista_inv(0)
        btn_modo_ciclico.on_click = lambda e: cambiar_subvista_inv(1)
        btn_modo_traz.on_click = lambda e: cambiar_subvista_inv(2)
        btn_modo_desv.on_click = lambda e: cambiar_subvista_inv(3)

        barra_titulo = ft.Container(
            padding=ft.Padding.symmetric(horizontal=16, vertical=10), bgcolor="#222A2C", border_radius=8, border=ft.Border.all(1, BORDER_COLOR),
            content=ft.Row([
                ft.Row([
                    ft.Icon(ft.Icons.LIBRARY_BOOKS_OUTLINED, color=ACCENT_CYAN, size=22),
                    ft.Text("MÓDULO DE INVENTARIO: PASILLOS, CONTEO CÍCLICO DIRIGIDO Y TRAZABILIDAD", size=14, weight=ft.FontWeight.W_900, color=TEXT_WHITE),
                ], spacing=8),
                ft.Row([
                    btn_modo_control, btn_modo_ciclico, btn_modo_traz, btn_modo_desv,
                    ft.IconButton(icon=ft.Icons.SYNC_ROUNDED, icon_color=ACCENT_CYAN, tooltip="Sincronizar Datos y Conteos", on_click=lambda e: actualizar_todos_los_datos()),
                ], spacing=8, wrap=True),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
        )

        col_principal = ft.Column([barra_titulo, contenedor_subvista_inv], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

        self.vista = ft.Container(padding=14, bgcolor=BG_MODULO, content=col_principal, expand=True)
        self.cambiar_subvista_inv_func = cambiar_subvista_inv
        self.actualizar_todos_los_datos_func = actualizar_todos_los_datos

        def carga_inicial_segura():
            import time
            time.sleep(0.4)
            actualizar_todos_los_datos()

        threading.Thread(target=carga_inicial_segura, daemon=True).start()

    def sel_sub_inventario(self, idx: int):
        mapa_idx = {0: 0, 1: 1, 2: 2, 3: 3, 4: 2, 5: 3}
        self.cambiar_subvista_inv_func(mapa_idx.get(idx, 0))