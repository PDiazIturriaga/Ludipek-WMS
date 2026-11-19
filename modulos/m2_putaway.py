import os
import time
import inspect
import re
from datetime import datetime
import pandas as pd
import flet as ft
from dependencias import *


class PutawayModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables

        # --- 1. PALETA OSCURA (ESTILO MONITOR INDUSTRIAL) ---
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

        # --- 2. VARIABLES DE ESTADO ---
        lpns_en_anden = []
        stock_en_racks = []
        mapa_descripciones_sku = {}
        mapa_multiplos_sku = {}
        mapa_picking_fijo = {}   # sku -> ubicación de picking asignada (wms_ubicacion_picking_sku)
        zona_seleccionada = "TODOS_RACKS"
        ubicaciones_bodega = []          # códigos de bodega_ubicaciones (para ocupación y gemelo 3D)
        ultima_bodega_sincronizada = None

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

        # --- 3. FUNCIONES AUXILIARES DE UI ---
        def notificar(texto: str, color: str = "#0284C7"):
            from dependencias import notificar_global
            notificar_global(self.page, texto, color)

        def reimprimir_desde_fila(lpn_cod: str):
            from dependencias import reimprimir_desde_fila_global
            reimprimir_desde_fila_global(self.page, lpn_cod)

        def tarjeta_dark(contenido, padding=14, expand_val=None, height_val=None, width_val=None):
            t = ft.Container(
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
            if isinstance(self.tarjetas_adaptables, list):
                self.tarjetas_adaptables.append(t)
            return t

        def texto_dark(label: str, width: int = None, expand=None, value: str = "", on_change=None):
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
                label=label, width=width, expand=expand, value=value, options=opts,
                dense=True, color=TEXT_WHITE, bgcolor=BG_INPUT, border_color=BORDER_COLOR,
                focused_border_color=ACCENT_CYAN, text_style=ft.TextStyle(size=12, color=TEXT_WHITE),
                label_style=ft.TextStyle(size=11, color=TEXT_MUTED),
                content_padding=ft.Padding.symmetric(horizontal=12, vertical=8), border_radius=6,
            )

        def crear_caja_digital(txt_control: ft.Text, etiqueta_inf: str, color_borde: str = "#6366F1", ancho: int = 88):
            return ft.Column(
                [
                    ft.Container(
                        width=ancho,
                        height=58,
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

        # --- 4. PAGINACIÓN SUPABASE Y CLASIFICADOR DE RACKS ---
        def cargar_tabla_paginada(tabla: str, max_filas: int = 4000, filtrar_bodega: bool = False) -> list:
            acumulado = []
            paso = 1000
            bodega_act = obtener_bodega_actual()
            for offset in range(0, max_filas, paso):
                res = supabase.table(tabla).select("*").range(offset, offset + paso - 1).execute()
                lote = res.data or []
                if filtrar_bodega:
                    acumulado.extend([f for f in lote if coincide_bodega_fila(f, bodega_act)])
                else:
                    acumulado.extend(lote)
                if len(lote) < paso:
                    break
            return acumulado

        ZONAS_ARENA = {"MK": "ARENA MARKETING", "BE": "ARENA BODEGA E", "ME": "MERMA ARENA"}
        COLOR_ARENA = "#D4A373"

        def clasificar_rack_y_nivel(codigo_ubicacion: str) -> tuple:
            ubi = str(codigo_ubicacion or "").strip().upper()
            if not ubi or ubi in ("ANDEN", "RECEPCION", "PENDIENTE", "SIN UBICACION", "NONE", "NULL"):
                return ("RECEPCION", "ANDÉN RECEPCIÓN", 0)
            # Zonas de arena (posiciones de piso, 2 pallets apilados): MK/BE = arena, ME = mermas de arena
            m_arena = re.match(r"^(MK|ME|BE)-\d{2}-\d{2}$", ubi)
            if m_arena:
                return (ZONAS_ARENA[m_arena.group(1)], "ARENA (PISO)", 0)
            partes = ubi.replace("_", "-").split("-")
            prefijo = partes[0].strip() if partes else "A"
            letra = prefijo[0] if prefijo else "A"
            rack_nombre = f"RACK {letra}"

            nivel_num = 2
            if len(partes) >= 3:
                ult = partes[-1].replace("N", "").replace("P", "").strip()
                try:
                    nivel_num = int(ult)
                except Exception:
                    nivel_num = 2
            elif "N1" in ubi or ubi.endswith("-01") or ubi.endswith("-1"):
                nivel_num = 1

            zona_nivel_str = "PICKING NIVEL 1" if nivel_num <= 1 else "RESERVA ALTURA"
            return (rack_nombre, zona_nivel_str, nivel_num)

        def formatear_fecha_vista(valor_f) -> str:
            s = str(valor_f or "").strip()
            if not s or s in ("None", "null", "S/F", "-"):
                return "S/F"
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
                try:
                    return datetime.strptime(s[:10], fmt).strftime("%d-%m-%Y")
                except ValueError:
                    continue
            return s[:10]

        def parsear_fecha_fefo(valor_f) -> datetime:
            """Convierte una fecha de vencimiento en datetime para ordenar candidatos FEFO (primero en vencer, primero en bajar)."""
            s = str(valor_f or "").strip()
            if not s or s.upper() in ("NONE", "NULL", "S/F", "-"):
                return datetime(2099, 12, 31)
            for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
                try:
                    return datetime.strptime(s[:10], fmt)
                except ValueError:
                    continue
            return datetime(2099, 12, 31)

        # --- 5. CONTROLES Y CONTADORES DIGITALES ---
        lbl_dig_anden = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color=ACCENT_AMBER, font_family="Consolas")
        lbl_dig_racks = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_dig_picking_n1 = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color=ACCENT_GREEN, font_family="Consolas")
        lbl_dig_reserva_alt = ft.Text("0", size=22, weight=ft.FontWeight.W_900, color=ACCENT_PURPLE, font_family="Consolas")

        lbl_dig_unid_zona = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color=TEXT_WHITE, font_family="Consolas")
        lbl_dig_skus_zona = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_dig_pos_ocup = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color="#34D399", font_family="Consolas")
        lbl_dig_alertas_reapro = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color="#F87171", font_family="Consolas")

        fila_botones_zonas = ft.Row(spacing=12, wrap=True, alignment=ft.MainAxisAlignment.START)
        fila_barras_racks = ft.Row(
            spacing=18,
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
            vertical_alignment=ft.CrossAxisAlignment.END,
            scroll=ft.ScrollMode.AUTO,
        )

        lbl_titulo_tabla_monitor = ft.Text(
            "MAPA EN VIVO DE STOCK EN RACKS (APP MÓVIL RF)",
            size=13,
            weight=ft.FontWeight.BOLD,
            color=ACCENT_CYAN,
        )
        lbl_subtitulo_tabla_monitor = ft.Text(
            "Haz clic en los botones superiores (Recepción, Rack A, Rack B...) para filtrar por zona.",
            size=11,
            color=TEXT_MUTED,
        )

        # Controles de la Zona Consultador (Separada)
        txt_cons_buscar = texto_dark(
            label="Buscar por SKU, LPN, Lote, Descripción o Ubicación (Ej: A-01-02)...",
            expand=True,
        )
        dd_cons_zona = dropdown_dark(
            label="Zona / Rack",
            width=205,
            value="TODOS",
            options=[
                opt_w("TODOS", "TODO EL CD (RACKS + ANDÉN)"),
                opt_w("SOLO_RACKS", "SOLO EN RACKS"),
                opt_w("RECEPCION", "SOLO EN RECEPCIÓN"),
                opt_w("RACK A", "RACK A"),
                opt_w("RACK B", "RACK B"),
                opt_w("RACK C", "RACK C"),
                opt_w("RACK D", "RACK D"),
            ],
        )
        dd_cons_nivel = dropdown_dark(
            label="Nivel Operativo",
            width=190,
            value="TODOS",
            options=[
                opt_w("TODOS", "TODOS LOS NIVELES"),
                opt_w("PICKING NIVEL 1", "NIVEL 1 (PICKING)"),
                opt_w("RESERVA ALTURA", "NIVEL 2+ (RESERVA)"),
                opt_w("ARENA (PISO)", "ARENA (PISO)"),
                opt_w("ANDÉN RECEPCIÓN", "ANDÉN RECEPCIÓN"),
            ],
        )
        dd_cons_qa = dropdown_dark(
            label="Estado QA",
            width=155,
            value="TODOS",
            options=[
                opt_w("TODOS", "TODOS"),
                opt_w("APROBADO", "APROBADO"),
                opt_w("CUARENTENA", "CUARENTENA"),
                opt_w("RECHAZADO", "RECHAZADO"),
            ],
        )

        lbl_cons_res_lpns = ft.Text("0 LPNs", size=17, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_cons_res_unid = ft.Text("0 UN", size=17, weight=ft.FontWeight.W_900, color="#34D399", font_family="Consolas")
        lbl_cons_res_skus = ft.Text("0 SKUs", size=17, weight=ft.FontWeight.W_900, color=TEXT_WHITE, font_family="Consolas")
        lbl_cons_res_ubic = ft.Text("0 Ubic.", size=17, weight=ft.FontWeight.W_900, color=ACCENT_AMBER, font_family="Consolas")

        # --- 6. TABLAS ---
        cols_stock = [
            ("UBICACIÓN", ACCENT_CYAN),
            ("RACK / ZONA", TEXT_WHITE),
            ("NIVEL OPERATIVO", TEXT_MUTED),
            ("LPN PALLET", ACCENT_CYAN),
            ("SKU", TEXT_WHITE),
            ("DESCRIPCIÓN", TEXT_MUTED),
            ("UNIDADES", "#34D399"),
            ("LOTE", TEXT_WHITE),
            ("VENCIMIENTO", TEXT_WHITE),
            ("CALIDAD (QA)", TEXT_WHITE),
            ("ETIQUETA", TEXT_WHITE),
        ]
        tabla_monitor_zona = ft.DataTable(
            heading_row_color=UI["card_alt"], heading_row_height=38, data_row_min_height=40, data_row_max_height=48,
            column_spacing=20, horizontal_margin=14, divider_thickness=0.5,
            columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in ["Ubicación", "Zona", "Nivel", "LPN", "SKU", "Descripción", "Unidades", "Lote", "Vencimiento", "Calidad", ""]],
            rows=[],
        )
        tabla_consultador_avanzado = ft.DataTable(
            heading_row_color=UI["card_alt"], heading_row_height=38, data_row_min_height=40, data_row_max_height=48,
            column_spacing=20, horizontal_margin=14, divider_thickness=0.5,
            columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in ["Ubicación", "Zona", "Nivel", "LPN", "SKU", "Descripción", "Unidades", "Lote", "Vencimiento", "Calidad", ""]],
            rows=[],
        )
        tabla_reabastecimiento = ft.DataTable(
            heading_row_color=UI["card_alt"], heading_row_height=38, data_row_min_height=40, data_row_max_height=48,
            column_spacing=20, horizontal_margin=14, divider_thickness=0.5,
            columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in ["Prioridad", "SKU", "Descripción", "Stock nivel 1", "Stock reserva", "Bajar este LPN (FEFO)", "Desde", ""]],
            rows=[],
        )

        cont_tabla_monitor = ui_tabla(tabla_monitor_zona, 460)
        cont_tabla_consultador = ui_tabla(tabla_consultador_avanzado, 520)
        cont_tabla_reapro = ui_tabla(tabla_reabastecimiento, 520)
        fila_racks = ft.ResponsiveRow(spacing=12, run_spacing=12)
        col_ocupacion_gemelo = ft.Column(spacing=10, tight=True)
        txt_buscar_zona = ft.TextField(
            label="Filtrar esta zona (SKU, LPN, lote, ubicación)", prefix_icon=ft.Icons.SEARCH_ROUNDED, width=360, dense=True,
            text_size=12.5, color=UI["texto"], bgcolor=UI["input"], border_color=UI["borde"], focused_border_color=UI["acento"],
            label_style=ft.TextStyle(size=11.5, color=UI["texto_2"]), border_radius=8,
        )

        # --- 7. SINCRONIZACIÓN DE DATOS CON SUPABASE ---
        def construir_item_stock(
            ubi_cod: str,
            lpn_u: str,
            sku_u: str,
            unid_u: int,
            cajas_u: int,
            lote_raw: str,
            venc_raw,
            desc_extra: str = "",
        ) -> dict:
            lote_limpio, qa_est = extraer_estado_qa(lote_raw or "S/L")
            venc_str = formatear_fecha_vista(venc_raw)
            rack_nom, zona_niv_str, niv_num = clasificar_rack_y_nivel(ubi_cod)
            return {
                "ubicacion": ubi_cod,
                "rack": rack_nom,
                "zona_nivel": zona_niv_str,
                "nivel_num": niv_num,
                "lpn": lpn_u or "S/LPN",
                "sku": sku_u or "-",
                "descripcion": mapa_descripciones_sku.get(sku_u, desc_extra or "Producto Almacenado"),
                "unidades": unid_u,
                "cajas": cajas_u,
                "lote": lote_limpio,
                "vencimiento": venc_str,
                "qa": qa_est,
                "bodega": obtener_bodega_actual(),
            }

        def sincronizar_datos_supabase():
            nonlocal lpns_en_anden, stock_en_racks, mapa_descripciones_sku, mapa_multiplos_sku, ultima_bodega_sincronizada, ubicaciones_bodega, mapa_picking_fijo
            bodega_act = obtener_bodega_actual()
            try:
                ubicaciones_bodega = sorted({
                    str(u.get("codigo_ubicacion") or "").strip().upper()
                    for u in leer_tabla_paginada(lambda: supabase.table("bodega_ubicaciones").select("codigo_ubicacion, bodega").eq("bodega", bodega_act))
                    if u.get("codigo_ubicacion") and not str(u.get("codigo_ubicacion")).upper().startswith("ZONA")
                })
            except Exception as ex_u:
                print(f"[WARN] Ubicaciones de {bodega_act}: {ex_u}")
                ubicaciones_bodega = []
            try:
                filas_mae = cargar_tabla_paginada("maestra_sku", 4000, filtrar_bodega=False)
                mapa_descripciones_sku = {}
                mapa_multiplos_sku = {}
                for m in filas_mae:
                    s_k = str(m.get("sku", "")).strip().upper()
                    if s_k:
                        if m.get("descripcion"):
                            mapa_descripciones_sku[s_k] = str(m.get("descripcion") or "")
                        try:
                            mult_m = max(1, int(float(m.get("multiplo") or 1)))
                            if mult_m > mapa_multiplos_sku.get(s_k, 1):
                                mapa_multiplos_sku[s_k] = mult_m
                        except Exception:
                            pass
            except Exception:
                mapa_descripciones_sku = {}
            try:
                filas_pf = supabase.table("wms_ubicacion_picking_sku").select("sku, ubicacion").eq(
                    "bodega", obtener_bodega_activa(self.page)).execute().data or []
                mapa_picking_fijo = {str(f.get("sku") or "").upper(): str(f.get("ubicacion") or "").upper() for f in filas_pf}
            except Exception:
                mapa_picking_fijo = {}
                mapa_multiplos_sku = {}

            mapa_rec_por_lpn = {}
            filas_recepcion = []
            try:
                filas_recepcion = cargar_tabla_paginada("registro_recepcion", 4000, filtrar_bodega=True)
                for r in filas_recepcion:
                    lpn_k = str(r.get("lpn") or "").strip().upper()
                    if lpn_k:
                        mapa_rec_por_lpn[lpn_k] = r
            except Exception:
                filas_recepcion = []

            ubicados_map = {}
            lpns_ubicados_set = set()

            for nom_tabla in ("bodega_inventario_ubicacion",):
                # Si la tabla principal ya cargó el inventario de los racks, evitamos llamadas HTTP innecesarias a las tablas secundarias
                if nom_tabla != "bodega_inventario_ubicacion" and ubicados_map:
                    continue
                try:
                    filas_u = cargar_tabla_paginada(nom_tabla, 4000, filtrar_bodega=True)
                    for row_u in filas_u:
                        ubi_cod = str(
                            row_u.get("ubicacion")
                            or row_u.get("codigo_ubicacion")
                            or row_u.get("posicion")
                            or ""
                        ).strip().upper()
                        lpn_u = str(
                            row_u.get("lpn")
                            or row_u.get("codigo_lpn")
                            or row_u.get("pallet")
                            or ""
                        ).strip().upper()
                        sku_u = str(row_u.get("sku") or "").strip().upper()
                        if not ubi_cod or (not lpn_u and not sku_u):
                            continue
                        if ubi_cod in ("ANDEN", "RECEPCION", "PENDIENTE", "SIN UBICACION", "NONE", "NULL"):
                            continue

                        info_rec = mapa_rec_por_lpn.get(lpn_u, {})
                        sku_f = sku_u or str(info_rec.get("sku") or "-").strip().upper()
                        unid_f = int(
                            row_u.get("cantidad_unidades")
                            or row_u.get("unidades")
                            or row_u.get("unidades_totales")
                            or row_u.get("cantidad")
                            or info_rec.get("unidades_totales")
                            or 0
                        )
                        if unid_f <= 0 and not lpn_u:
                            continue

                        cajas_f = int(row_u.get("cajas") or info_rec.get("cajas") or 1)
                        lote_f = str(row_u.get("lote") or info_rec.get("lote") or "S/L")
                        venc_f = (
                            row_u.get("fecha_vencimiento_cl")
                            or row_u.get("vencimiento")
                            or info_rec.get("fecha_vencimiento_cl")
                        )
                        clave_u = (ubi_cod, lpn_u or f"{sku_f}_{row_u.get('id')}")
                        if clave_u not in ubicados_map:
                            ubicados_map[clave_u] = construir_item_stock(
                                ubi_cod,
                                lpn_u,
                                sku_f,
                                unid_f,
                                cajas_f,
                                lote_f,
                                venc_f,
                                str(row_u.get("descripcion") or ""),
                            )
                            if lpn_u:
                                lpns_ubicados_set.add(lpn_u)
                except Exception:
                    continue

            for r in filas_recepcion:
                lpn_r = str(r.get("lpn") or "").strip().upper()
                ubi_r = str(
                    r.get("ubicacion")
                    or r.get("codigo_ubicacion")
                    or r.get("ubicacion_actual")
                    or ""
                ).strip().upper()
                if ubi_r and ubi_r not in ("ANDEN", "RECEPCION", "PENDIENTE", "SIN UBICACION", "NONE", "NULL"):
                    sku_r = str(r.get("sku") or "-").strip().upper()
                    clave_u = (ubi_r, lpn_r or sku_r)
                    if clave_u not in ubicados_map:
                        ubicados_map[clave_u] = construir_item_stock(
                            ubi_r,
                            lpn_r,
                            sku_r,
                            int(r.get("unidades_totales") or 0),
                            int(r.get("cajas") or 1),
                            str(r.get("lote") or "S/L"),
                            r.get("fecha_vencimiento_cl"),
                        )
                    if lpn_r:
                        lpns_ubicados_set.add(lpn_r)

            stock_en_racks = sorted(ubicados_map.values(), key=lambda x: (x["ubicacion"], x["lpn"]))

            anden_temp = []
            vistos_anden = set()
            for r in filas_recepcion:
                lpn_r = str(r.get("lpn") or "").strip().upper()
                if not lpn_r or lpn_r in lpns_ubicados_set or lpn_r in vistos_anden:
                    continue
                vistos_anden.add(lpn_r)
                sku_r = str(r.get("sku") or "-").strip().upper()
                anden_temp.append(
                    construir_item_stock(
                        "ANDÉN RECEPCIÓN",
                        lpn_r,
                        sku_r,
                        int(r.get("unidades_totales") or 0),
                        int(r.get("cajas") or 1),
                        str(r.get("lote") or "S/L"),
                        r.get("fecha_vencimiento_cl"),
                        "En Andén Recepción",
                    )
                )
            lpns_en_anden = anden_temp
            ultima_bodega_sincronizada = bodega_act

        # --- 8. COMPONENTES DINÁMICOS (BOTONES DE RACKS Y FILAS DE TABLA) ---
        def chip(texto: str, color: str):
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=8, vertical=3), border_radius=12,
                bgcolor=ft.Colors.with_opacity(0.14, color), border=ft.Border.all(1, ft.Colors.with_opacity(0.5, color)),
                content=ft.Text(texto, size=11, weight=ft.FontWeight.W_600, color=color),
            )

        def crear_fila_tabla_stock(it: dict) -> ft.DataRow:
            es_anden = it["rack"] == "RECEPCION"
            zona_txt = "Andén" if es_anden else it["rack"].replace("RACK ", "Rack ")
            if es_anden:
                nivel = chip("Andén", UI["alerta"])
            elif it["rack"] == "MERMA ARENA":
                nivel = chip("Merma arena", UI["peligro"])
            elif it["nivel_num"] == 0:
                nivel = chip("Arena piso", COLOR_ARENA)
            elif it["nivel_num"] == 1:
                nivel = chip("Picking N1", UI["exito"])
            else:
                nivel = chip(f"Reserva N{it['nivel_num']}", UI["acento"])
            qa_val = it["qa"]
            qa = chip("Aprobado", UI["exito"]) if qa_val == "APROBADO" else (chip("Cuarentena", UI["alerta"]) if qa_val == "CUARENTENA" else chip("Rechazado", UI["peligro"]))
            lpn_c = it["lpn"]
            return ft.DataRow(cells=[
                ft.DataCell(ft.Text(it["ubicacion"], weight=ft.FontWeight.W_700, size=12.5, color=UI["texto"])),
                ft.DataCell(ft.Text(zona_txt, size=12, color=UI["texto_2"])),
                ft.DataCell(nivel),
                ft.DataCell(ft.Text(lpn_c, size=12, color=UI["texto"])),
                ft.DataCell(ft.Text(it["sku"], weight=ft.FontWeight.W_600, size=12, color=UI["texto"])),
                ft.DataCell(ft.Text(it["descripcion"][:36], size=12, color=UI["texto_2"], tooltip=it["descripcion"])),
                ft.DataCell(ft.Text(f"{it['unidades']:,}".replace(",", "."), weight=ft.FontWeight.W_700, size=12.5, color=UI["texto"])),
                ft.DataCell(ft.Text(it["lote"], size=12, color=UI["texto"])),
                ft.DataCell(ft.Text(it["vencimiento"], size=12, color=UI["texto"])),
                ft.DataCell(qa),
                ft.DataCell(ft.IconButton(icon=ft.Icons.PRINT_OUTLINED, icon_size=18, icon_color=UI["acento"],
                                          tooltip="Reimprimir etiqueta LPN 15x10",
                                          on_click=lambda ev, cod=lpn_c: reimprimir_desde_fila(cod))),
            ])

        def crear_boton_zona_rack(
            clave_zona: str,
            titulo: str,
            icono,
            cant_lpns: int,
            cant_unidades: int,
            cant_skus: int,
            color_acento: str,
            fn_click,
        ):
            es_activo = zona_seleccionada == clave_zona
            return ft.Container(
                width=180,
                padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                bgcolor="#232D30" if es_activo else "#181E20",
                border_radius=8,
                border=ft.Border.all(2 if es_activo else 1, color_acento if es_activo else BORDER_COLOR),
                ink=True,
                on_click=fn_click,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(icono, color=color_acento, size=17),
                                ft.Text(titulo, size=11, weight=ft.FontWeight.W_900, color=TEXT_WHITE, expand=True),
                            ],
                            spacing=6,
                        ),
                        ft.Container(
                            padding=ft.Padding.symmetric(horizontal=8, vertical=5),
                            bgcolor=BG_DIGITAL,
                            border_radius=6,
                            border=ft.Border.all(1, color_acento if es_activo else "#2E383B"),
                            alignment=ft.Alignment.CENTER,
                            content=ft.Row(
                                [
                                    ft.Text(
                                        f"{cant_lpns}",
                                        size=21,
                                        weight=ft.FontWeight.W_900,
                                        color=color_acento if es_activo else TEXT_WHITE,
                                        font_family="Consolas",
                                    ),
                                    ft.Text("LPNs", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
                                ],
                                alignment=ft.MainAxisAlignment.CENTER,
                                spacing=6,
                            ),
                        ),
                        ft.Row(
                            [
                                ft.Text(f"{cant_unidades:,} UN".replace(",", "."), size=10, weight=ft.FontWeight.BOLD, color="#34D399"),
                                ft.Text(f"{cant_skus} SKUs", size=10, color=TEXT_MUTED),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=5,
                ),
            )

        def ejecutar_filtro_consultador(e=None):
            texto_b = (txt_cons_buscar.value or "").strip().upper()
            zona_f = dd_cons_zona.value or "TODOS"
            nivel_f = dd_cons_nivel.value or "TODOS"
            qa_f = dd_cons_qa.value or "TODOS"

            universo = list(stock_en_racks) + list(lpns_en_anden)
            filtrados = []
            for it in universo:
                if zona_f == "SOLO_RACKS" and it["rack"] == "RECEPCION":
                    continue
                elif zona_f == "RECEPCION" and it["rack"] != "RECEPCION":
                    continue
                elif zona_f not in ("TODOS", "SOLO_RACKS", "RECEPCION") and it["rack"] != zona_f:
                    continue
                if nivel_f != "TODOS" and it["zona_nivel"] != nivel_f:
                    continue
                if qa_f != "TODOS" and it["qa"] != qa_f:
                    continue
                if texto_b:
                    busq = f"{it['ubicacion']} {it['rack']} {it['lpn']} {it['sku']} {it['descripcion']} {it['lote']} {it['vencimiento']}".upper()
                    if texto_b not in busq:
                        continue
                filtrados.append(it)

            lbl_cons_res_lpns.value = f"{len({x['lpn'] for x in filtrados})} LPNs"
            lbl_cons_res_unid.value = f"{sum(x['unidades'] for x in filtrados):,} UN".replace(",", ".")
            lbl_cons_res_skus.value = f"{len({x['sku'] for x in filtrados})} SKUs"
            lbl_cons_res_ubic.value = f"{len({x['ubicacion'] for x in filtrados})} Ubic."

            tabla_consultador_avanzado.rows = [crear_fila_tabla_stock(it) for it in filtrados[:250]]
            page.update()

        def limpiar_filtros_consultador(e=None):
            txt_cons_buscar.value = ""
            dd_cons_zona.value = "TODOS"
            dd_cons_nivel.value = "TODOS"
            dd_cons_qa.value = "TODOS"
            ejecutar_filtro_consultador()

        def exportar_excel_consultador(e=None):
            universo = list(stock_en_racks) + list(lpns_en_anden)
            if not universo:
                notificar("No hay datos para exportar.", "#D97706")
                return
            try:
                bodega_act = obtener_bodega_actual()
                os.makedirs("reportes_recepcion", exist_ok=True)
                df_exp = pd.DataFrame(
                    [
                        {
                            "Bodega": bodega_act,
                            "Zona / Rack": x["rack"],
                            "Ubicacion": x["ubicacion"],
                            "Nivel": x["zona_nivel"],
                            "LPN": x["lpn"],
                            "SKU": x["sku"],
                            "Descripcion": x["descripcion"],
                            "Unidades": x["unidades"],
                            "Cajas": x["cajas"],
                            "Lote": x["lote"],
                            "Vencimiento": x["vencimiento"],
                            "QA": x["qa"],
                        }
                        for x in universo
                    ]
                )
                ruta_xlsx = os.path.join(
                    "reportes_recepcion",
                    f"Stock_Ubicaciones_{bodega_act.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                )
                df_exp.to_excel(ruta_xlsx, index=False)
                notificar(f"Excel exportado ({bodega_act}): {ruta_xlsx}", "#047857")
                descargar_o_abrir_archivo(self.page, ruta_xlsx)
            except Exception as ex:
                notificar(f"Error exportando Excel: {ex}", "#B91C1C")

        txt_cons_buscar.on_change = ejecutar_filtro_consultador
        # En Flet 0.70+ Dropdown solo dispara on_select (on_change ya no existe)
        dd_cons_zona.on_select = ejecutar_filtro_consultador
        dd_cons_nivel.on_select = ejecutar_filtro_consultador
        dd_cons_qa.on_select = ejecutar_filtro_consultador

        def renderizar_todo_el_modulo():
            bodega_act = obtener_bodega_actual()
            racks_base = ["RACK A", "RACK B", "RACK C", "RACK D"]
            for rk in sorted({x["rack"] for x in stock_en_racks if x["rack"].startswith("RACK ")}):
                if rk not in racks_base:
                    racks_base.append(rk)

            dd_cons_zona.options = [
                opt_w("TODOS", "TODO EL CD (RACKS + ANDÉN)"),
                opt_w("SOLO_RACKS", "SOLO EN RACKS"),
                opt_w("RECEPCION", "SOLO EN RECEPCIÓN"),
            ] + [opt_w(rk, rk) for rk in racks_base] + [opt_w(z, z) for z in ZONAS_ARENA.values()]

            def sel_zona(nueva_z: str):
                nonlocal zona_seleccionada
                zona_seleccionada = nueva_z
                renderizar_todo_el_modulo()

            # Ocupación por rack: posiciones de la maestra vs posiciones con stock
            pos_por_rack = {}
            for cod in ubicaciones_bodega:
                pos_por_rack.setdefault(clasificar_rack_y_nivel(cod)[0], set()).add(cod)
            ocup_por_rack = {}
            for x in stock_en_racks:
                ocup_por_rack.setdefault(x["rack"], set()).add(x["ubicacion"])
            for rk in pos_por_rack:
                if rk.startswith("RACK ") and rk not in racks_base:
                    racks_base.append(rk)
            racks_base.sort()

            def tarjeta_zona(clave, titulo, icono, color, items, ocupadas=None, total=None):
                activo = zona_seleccionada == clave
                pct = (ocupadas / total) if total else None
                return ft.Container(
                    col={"xs": 6, "md": 4, "lg": 2},
                    padding=12, border_radius=10, ink=True,
                    on_click=lambda e, c=clave: sel_zona(c),
                    bgcolor=ft.Colors.with_opacity(0.10, color) if activo else UI["card_alt"],
                    border=ft.Border.all(1.5 if activo else 1, color if activo else UI["borde"]),
                    content=ft.Column([
                        ft.Row([ft.Icon(icono, size=16, color=color),
                                ft.Text(titulo, size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"])], spacing=6),
                        ft.Row([
                            ft.Text(str(len(items)), size=22, weight=ft.FontWeight.W_700, color=UI["texto"]),
                            ft.Text("LPN", size=11, color=UI["texto_2"]),
                        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.END),
                        ft.Text(f"{sum(x['unidades'] for x in items):,} UN · {len({x['sku'] for x in items})} SKU".replace(",", "."),
                                size=11, color=UI["texto_2"]),
                        *([ft.ProgressBar(value=min(1.0, pct), height=5, color=color, bgcolor="#2A3538", border_radius=3),
                           ft.Text(f"{ocupadas}/{total} posiciones · {int(round(pct * 100))}%", size=10.5, color=UI["texto_3"])]
                          if pct is not None else []),
                    ], spacing=4, tight=True),
                )

            total_pos = sum(len(v) for k, v in pos_por_rack.items() if k.startswith("RACK "))
            total_ocup = sum(len(ocup_por_rack.get(k, set()) & v) for k, v in pos_por_rack.items() if k.startswith("RACK "))
            stock_solo_racks = [x for x in stock_en_racks if x["rack"].startswith("RACK ")]
            tarjetas = [
                tarjeta_zona("RECEPCION", "Andén", ft.Icons.MOVE_TO_INBOX_ROUNDED, UI["alerta"], lpns_en_anden),
                tarjeta_zona("TODOS_RACKS", "Todos los racks", ft.Icons.WAREHOUSE_OUTLINED, UI["acento"], stock_solo_racks,
                             total_ocup, total_pos),
            ]
            for nom_rk in racks_base:
                items_r = [x for x in stock_en_racks if x["rack"] == nom_rk]
                pos_r = pos_por_rack.get(nom_rk, set())
                tarjetas.append(tarjeta_zona(nom_rk, nom_rk.replace("RACK ", "Rack "), ft.Icons.VIEW_COLUMN_OUTLINED, "#818CF8",
                                             items_r, len(ocup_por_rack.get(nom_rk, set()) & pos_r) if pos_r else None, len(pos_r) or None))
            # Zonas de arena: ocupación = posiciones con al menos un pallet
            for nom_ar in ZONAS_ARENA.values():
                pos_ar = pos_por_rack.get(nom_ar, set())
                items_ar = [x for x in stock_en_racks if x["rack"] == nom_ar]
                if not pos_ar and not items_ar:
                    continue
                tarjetas.append(tarjeta_zona(
                    nom_ar, nom_ar.title(),
                    ft.Icons.GRASS_ROUNDED if nom_ar != "MERMA ARENA" else ft.Icons.DELETE_OUTLINE_ROUNDED,
                    COLOR_ARENA if nom_ar != "MERMA ARENA" else UI["peligro"], items_ar,
                    len(ocup_por_rack.get(nom_ar, set()) & pos_ar) if pos_ar else None, len(pos_ar) or None))
            fila_racks.controls = tarjetas
            lbl_dig_ocupacion.value = f"{int(round(total_ocup * 100 / total_pos))}%" if total_pos else "—"
            lbl_det_ocupacion.value = f"{total_ocup} de {total_pos} posiciones con stock" if total_pos else "Sin maestra de ubicaciones"

            # Ocupación por rack para la pantalla del gemelo
            col_ocupacion_gemelo.controls = [
                ft.Row([
                    ft.Text(rk.replace("RACK ", "Rack "), size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"], width=70),
                    ft.Container(content=ft.ProgressBar(value=(len(ocup_por_rack.get(rk, set()) & pos_por_rack.get(rk, set())) / len(pos_por_rack[rk])) if pos_por_rack.get(rk) else 0,
                                                        height=8, color=UI["acento"], bgcolor="#2A3538", border_radius=4), expand=True),
                    ft.Text(f"{len(ocup_por_rack.get(rk, set()) & pos_por_rack.get(rk, set()))}/{len(pos_por_rack.get(rk, set()))}",
                            size=12, color=UI["texto_2"], width=70, text_align=ft.TextAlign.RIGHT),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                for rk in racks_base
            ]

            if zona_seleccionada == "RECEPCION":
                items_vista = lpns_en_anden
                lbl_titulo_tabla_monitor.value = f"Andén · {len(items_vista)} LPN pendientes de ubicar"
            elif zona_seleccionada == "TODOS_RACKS":
                items_vista = stock_solo_racks
                lbl_titulo_tabla_monitor.value = f"Todos los racks · {len(items_vista)} LPN"
            else:
                items_vista = [x for x in stock_en_racks if x["rack"] == zona_seleccionada]
                lbl_titulo_tabla_monitor.value = f"{zona_seleccionada.replace('RACK ', 'Rack ')} · {len(items_vista)} LPN"

            lbl_dig_anden.value = str(len(lpns_en_anden))
            lbl_dig_racks.value = str(len(stock_en_racks))
            lbl_dig_picking_n1.value = str(sum(1 for x in stock_en_racks if x["nivel_num"] == 1))
            lbl_dig_reserva_alt.value = str(sum(1 for x in stock_en_racks if x["nivel_num"] >= 2))

            lbl_dig_unid_zona.value = str(sum(x["unidades"] for x in items_vista))
            lbl_dig_skus_zona.value = str(len({x["sku"] for x in items_vista}))
            lbl_dig_pos_ocup.value = str(len({x["ubicacion"] for x in items_vista}))

            q_zona = (txt_buscar_zona.value or "").strip().upper()
            if q_zona:
                items_vista = [x for x in items_vista if q_zona in f"{x['ubicacion']} {x['lpn']} {x['sku']} {x['descripcion']} {x['lote']}".upper()]
            lbl_subtitulo_tabla_monitor.value = (f"{len(items_vista)} resultado(s) para «{q_zona}»" if q_zona else
                                                 "Toque un rack arriba para ver solo sus pallets.")
            tabla_monitor_zona.rows = [crear_fila_tabla_stock(it) for it in items_vista[:300]]

            # Alertas de Reabastecimiento (Reserva N2+ -> Picking N1) con ordenamiento FEFO real y umbral inteligente
            por_sku = {}
            for x in stock_en_racks:
                sk = x["sku"]
                if sk not in por_sku:
                    por_sku[sk] = {"n1": 0, "cajas_n1": 0, "res": 0, "cands": []}
                if x["nivel_num"] == 0:
                    continue  # arena: se despacha directo desde el piso, no se reabastece
                if x["nivel_num"] == 1:
                    por_sku[sk]["n1"] += x["unidades"]
                    por_sku[sk]["cajas_n1"] += int(x.get("cajas") or 1)
                else:
                    por_sku[sk]["res"] += x["unidades"]
                    por_sku[sk]["cands"].append(x)

            tabla_reabastecimiento.rows.clear()
            alertas_cnt = 0
            for sk, d_n in sorted(por_sku.items(), key=lambda i: (i[1]["n1"], i[0])):
                mult_sku = mapa_multiplos_sku.get(sk, 1)
                umbral_unid = max(2 * mult_sku, min(200, mult_sku * 4)) if mult_sku > 1 else 50
                requiere_reapro = d_n["res"] > 0 and (d_n["n1"] == 0 or d_n["cajas_n1"] <= 2 or d_n["n1"] < umbral_unid)

                if requiere_reapro:
                    alertas_cnt += 1
                    # Ordenar candidatos de Reserva por FEFO (vencimiento más próximo primero)
                    cands_fefo = sorted(
                        d_n["cands"],
                        key=lambda item_c: (parsear_fecha_fefo(item_c.get("vencimiento")), item_c.get("ubicacion", "")),
                    )
                    cand = cands_fefo[0]
                    crit = d_n["n1"] == 0
                    venc_cand_txt = f" ({cand['vencimiento']})" if cand.get("vencimiento") and cand["vencimiento"] != "S/F" else ""
                    tabla_reabastecimiento.rows.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(chip("Sin stock en N1" if crit else "Reabastecer", UI["peligro"] if crit else UI["alerta"])),
                                ft.DataCell(ft.Text(sk, weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(mapa_descripciones_sku.get(sk, "-")[:30], size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"{d_n['n1']} UN ({d_n['cajas_n1']} Cj)", weight=ft.FontWeight.BOLD, size=11, color="#F87171" if crit else ACCENT_AMBER)),
                                ft.DataCell(ft.Text(f"{d_n['res']} UN", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                                ft.DataCell(ft.Text(f"{cand['lpn']}{venc_cand_txt}", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(cand["ubicacion"], weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"Bajar a {mapa_picking_fijo[sk]}" if mapa_picking_fijo.get(sk) else "Sin picking asignado",
                                                    size=11.5, weight=ft.FontWeight.BOLD if mapa_picking_fijo.get(sk) else None,
                                                    color="#34D399" if mapa_picking_fijo.get(sk) else UI["texto_3"])),
                            ]
                        )
                    )
            lbl_dig_alertas_reapro.value = str(alertas_cnt)

            ejecutar_filtro_consultador()

        def cargar_inventario_ubicaciones(e=None):
            sincronizar_datos_supabase()
            renderizar_todo_el_modulo()
            actualizar_detalle_kpis()
            page.update()

        # --- 9. PANTALLAS DEL MÓDULO ---
        lbl_dig_ocupacion = ft.Text("—")
        lbl_det_ocupacion = ft.Text("", size=11, color=UI["texto_3"])
        lbl_det_racks = ft.Text("", size=11, color=UI["texto_3"])

        def actualizar_detalle_kpis():
            n1 = sum(1 for x in stock_en_racks if x["nivel_num"] == 1)
            res = sum(1 for x in stock_en_racks if x["nivel_num"] >= 2)
            ar = sum(1 for x in stock_en_racks if x["nivel_num"] == 0)
            lbl_det_racks.value = f"{n1} en picking N1 · {res} en reserva" + (f" · {ar} en arena" if ar else "")

        txt_buscar_zona.on_change = lambda e: renderizar_todo_el_modulo()

        def abrir_gemelo_3d(e=None):
            """Genera la página 3D con los datos actuales y la abre en una pestaña nueva."""
            from servicios.gemelo_3d import generar_html_gemelo
            if not stock_en_racks and not ubicaciones_bodega:
                sincronizar_datos_supabase()
            bodega_act = obtener_bodega_actual()
            html = generar_html_gemelo(bodega_act, ubicaciones_bodega, stock_en_racks, lpns_en_anden)
            nombre = f"gemelo_3d_{bodega_act.replace(' ', '_').lower()}.html"
            raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            for carpeta in {os.path.join(os.getcwd(), "assets", "descargas"), os.path.join(raiz, "assets", "descargas")}:
                try:
                    os.makedirs(carpeta, exist_ok=True)
                    with open(os.path.join(carpeta, nombre), "w", encoding="utf-8") as fh:
                        fh.write(html)
                except Exception as ex:
                    print(f"[WARN] Gemelo 3D: {ex}")
            url = f"/descargas/{nombre}?v={int(time.time())}"
            btn_ver_gemelo.url = url
            btn_ver_gemelo.visible = True

            async def _abrir():
                try:
                    r = self.page.launch_url(url, web_popup_window_name="_blank")
                    if inspect.iscoroutine(r):
                        await r
                except Exception:
                    pass
            try:
                self.page.run_task(_abrir)
            except Exception:
                pass
            notificar("Gemelo 3D generado. Si no se abrió, use el botón «Ver en pestaña nueva».", "#047857")
            page.update()

        # ---------- 1. Mapa de racks ----------
        tarjeta_tabla_zona = ft.Container(
            padding=16, bgcolor=UI["card"], border_radius=10, border=ft.Border.all(1, UI["borde"]),
            content=ft.Column([
                ft.Row([
                    lbl_titulo_tabla_monitor,
                    ft.Row([txt_buscar_zona,
                            ui_menu("Exportar", ft.Icons.DOWNLOAD_ROUNDED, [
                                ("Todo el stock por ubicación (Excel)", ft.Icons.TABLE_VIEW_ROUNDED, exportar_excel_consultador),
                            ])], spacing=8, wrap=True),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True, run_spacing=8),
                lbl_subtitulo_tabla_monitor,
                cont_tabla_monitor,
            ], spacing=10, tight=True),
        )
        vista_1_monitor_racks = ft.Column([
            ft.ResponsiveRow([
                ui_kpi(lbl_dig_anden, "Pendientes de ubicar", ft.Icons.MOVE_TO_INBOX_ROUNDED, UI["alerta"],
                       ft.Text("LPN recibidos sin almacenar", size=11, color=UI["texto_3"])),
                ui_kpi(lbl_dig_racks, "LPN en racks", ft.Icons.WAREHOUSE_OUTLINED, UI["acento"], lbl_det_racks),
                ui_kpi(lbl_dig_ocupacion, "Ocupación de racks", ft.Icons.GRID_VIEW_ROUNDED, "#818CF8", lbl_det_ocupacion),
                ui_kpi(lbl_dig_alertas_reapro, "Por reabastecer", ft.Icons.ARROW_DOWNWARD_ROUNDED, UI["peligro"],
                       ft.Text("SKU con poco stock en nivel 1", size=11, color=UI["texto_3"])),
            ], spacing=12, run_spacing=12),
            ui_tarjeta(fila_racks, titulo="Zonas y racks", subtitulo="Toque una tarjeta para ver sus pallets.",
                       icono=ft.Icons.VIEW_COLUMN_OUTLINED),
            tarjeta_tabla_zona,
        ], spacing=12)
        lbl_titulo_tabla_monitor.size = 14
        lbl_titulo_tabla_monitor.weight = ft.FontWeight.W_600
        lbl_titulo_tabla_monitor.color = UI["texto"]
        lbl_subtitulo_tabla_monitor.color = UI["texto_2"]

        # ---------- 2. Reabastecimiento ----------
        vista_2_reabastecimiento = ft.Column([
            ui_tarjeta(cont_tabla_reapro, titulo="SKU a bajar de reserva a nivel 1",
                       subtitulo="Ordenado por menor stock en nivel 1. El LPN sugerido es el que vence primero (FEFO).",
                       icono=ft.Icons.ARROW_DOWNWARD_ROUNDED),
        ], spacing=12)

        # ---------- 3. Buscar pallet / ubicación ----------
        txt_cons_buscar.prefix_icon = ft.Icons.SEARCH_ROUNDED
        resumen_busqueda = ft.Row([
            ft.Row([ft.Icon(ft.Icons.QR_CODE_2_ROUNDED, size=16, color=UI["texto_2"]), lbl_cons_res_lpns], spacing=6, tight=True),
            ft.Row([ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=16, color=UI["texto_2"]), lbl_cons_res_unid], spacing=6, tight=True),
            ft.Row([ft.Icon(ft.Icons.CATEGORY_OUTLINED, size=16, color=UI["texto_2"]), lbl_cons_res_skus], spacing=6, tight=True),
            ft.Row([ft.Icon(ft.Icons.PLACE_OUTLINED, size=16, color=UI["texto_2"]), lbl_cons_res_ubic], spacing=6, tight=True),
        ], spacing=22, wrap=True)
        for lbl in (lbl_cons_res_lpns, lbl_cons_res_unid, lbl_cons_res_skus, lbl_cons_res_ubic):
            lbl.size = 13
            lbl.weight = ft.FontWeight.W_600
            lbl.color = UI["texto"]
            lbl.font_family = None
        vista_3_consultador_aparte = ft.Column([
            ui_tarjeta(
                ft.Column([
                    ft.ResponsiveRow([
                        ft.Container(content=txt_cons_buscar, col={"xs": 12, "lg": 6}),
                        ft.Container(content=dd_cons_zona, col={"xs": 12, "sm": 4, "lg": 2}),
                        ft.Container(content=dd_cons_nivel, col={"xs": 12, "sm": 4, "lg": 2}),
                        ft.Container(content=dd_cons_qa, col={"xs": 12, "sm": 4, "lg": 2}),
                    ], spacing=10, run_spacing=10),
                    resumen_busqueda,
                    cont_tabla_consultador,
                ], spacing=12, tight=True),
                titulo="Buscar en racks y andén", icono=ft.Icons.MANAGE_SEARCH_ROUNDED,
                acciones=[
                    ui_boton("Limpiar", ft.Icons.FILTER_ALT_OFF_OUTLINED, limpiar_filtros_consultador, "texto"),
                    ui_boton("Exportar Excel", ft.Icons.DOWNLOAD_ROUNDED, exportar_excel_consultador, "secundario"),
                ],
            ),
        ], spacing=12)

        # ---------- 4. Gemelo digital 3D ----------
        btn_ver_gemelo = ft.Button(
            content=ft.Text("Ver en pestaña nueva", size=12, weight=ft.FontWeight.W_600),
            icon=ft.Icons.OPEN_IN_NEW_ROUNDED, height=36, visible=False, url="",
            bgcolor=UI["card_alt"], color=UI["texto"],
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6), side=ft.BorderSide(1, UI["borde"])),
        )
        vista_4_gemelo_digital = ft.Column([
            ft.Container(
                padding=24, border_radius=12,
                gradient=ft.LinearGradient(begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT,
                                           colors=["#0E3A4A", "#1B2122"]),
                border=ft.Border.all(1, UI["borde"]),
                content=ft.Row([
                    ft.Container(width=64, height=64, border_radius=14, bgcolor=ft.Colors.with_opacity(0.18, UI["acento"]),
                                 alignment=ft.Alignment.CENTER, content=ft.Icon(ft.Icons.VIEW_IN_AR_ROUNDED, size=36, color=UI["acento"])),
                    ft.Column([
                        ft.Text("Gemelo digital 3D de la bodega", size=20, weight=ft.FontWeight.W_700, color=UI["texto"]),
                        ft.Text("Racks, niveles y pallets en tres dimensiones con los datos actuales del WMS. "
                                "Gire con el mouse, haga zoom, busque un SKU o LPN y coloree por zona, vencimiento o calidad.",
                                size=12.5, color=UI["texto_2"]),
                        ft.Row([ui_boton("Abrir gemelo 3D", ft.Icons.VIEW_IN_AR_ROUNDED, abrir_gemelo_3d), btn_ver_gemelo],
                               spacing=10, wrap=True),
                    ], spacing=8, expand=True, tight=True),
                ], spacing=20, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ),
            ui_tarjeta(col_ocupacion_gemelo, titulo="Ocupación por rack", subtitulo="Posiciones con stock / posiciones de la maestra de ubicaciones.",
                       icono=ft.Icons.GRID_VIEW_ROUNDED),
        ], spacing=12)

        # ---------- Armado ----------
        vistas_put = [vista_1_monitor_racks, vista_2_reabastecimiento, vista_3_consultador_aparte, vista_4_gemelo_digital]
        titulos_put = [
            ("Mapa de racks", "Dónde están los pallets: andén, racks y niveles."),
            ("Reabastecimiento", "Qué bajar de reserva a nivel 1 para que picking no se quede sin stock."),
            ("Buscar pallet o ubicación", "Encuentre un LPN, SKU, lote o posición en toda la bodega."),
            ("Gemelo digital 3D", "La bodega en tres dimensiones con su stock actual."),
        ]
        contenedor_subvista_putaway = ft.Container(content=vista_1_monitor_racks)
        lbl_titulo_put = ft.Text(titulos_put[0][0], size=18, weight=ft.FontWeight.W_700, color=UI["texto"])
        lbl_sub_put = ft.Text(titulos_put[0][1], size=12, color=UI["texto_2"])

        def cambiar_subvista_interna(idx: int):
            idx = idx if 0 <= idx < len(vistas_put) else 0
            contenedor_subvista_putaway.content = vistas_put[idx]
            lbl_titulo_put.value, lbl_sub_put.value = titulos_put[idx]
            actualizar_detalle_kpis()
            page.update()

        encabezado = ft.Row([
            ft.Row([ft.Icon(ft.Icons.WAREHOUSE_OUTLINED, size=24, color=UI["acento"]),
                    ft.Column([lbl_titulo_put, lbl_sub_put], spacing=1, tight=True)],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ui_boton("Actualizar", ft.Icons.SYNC_ROUNDED, cargar_inventario_ubicaciones, "secundario"),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True)

        col_putaway = ft.Column([encabezado, contenedor_subvista_putaway], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

        self.vista = ft.Container(padding=ft.Padding.only(left=16, top=14, right=16, bottom=16), bgcolor=UI["bg"], content=col_putaway, expand=True)
        self.contenedor = contenedor_subvista_putaway
        self.cargar_inventario_ubicaciones_func = cargar_inventario_ubicaciones
        self.cambiar_subvista_interna_func = cambiar_subvista_interna
        self.obtener_ultima_bodega_func = lambda: ultima_bodega_sincronizada
        self.obtener_bodega_actual_func = obtener_bodega_actual

    def cargar_inventario_ubicaciones(self, e=None):
        self.cargar_inventario_ubicaciones_func(e)

    def sel_sub_put(self, idx: int):
        if self.obtener_ultima_bodega_func() != self.obtener_bodega_actual_func():
            self.cargar_inventario_ubicaciones_func()
        self.cambiar_subvista_interna_func(idx)
