import os
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
        zona_seleccionada = "TODOS_RACKS"

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
        def cargar_tabla_paginada(tabla: str, max_filas: int = 4000) -> list:
            acumulado = []
            paso = 1000
            for offset in range(0, max_filas, paso):
                res = supabase.table(tabla).select("*").range(offset, offset + paso - 1).execute()
                lote = res.data or []
                acumulado.extend(lote)
                if len(lote) < paso:
                    break
            return acumulado

        def clasificar_rack_y_nivel(codigo_ubicacion: str) -> tuple:
            ubi = str(codigo_ubicacion or "").strip().upper()
            if not ubi or ubi in ("ANDEN", "RECEPCION", "PENDIENTE", "SIN UBICACION", "NONE", "NULL"):
                return ("RECEPCION", "ANDÉN RECEPCIÓN", 0)
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
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=32,
            data_row_max_height=38,
            column_spacing=15,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[ft.DataColumn(ft.Text(t, weight=ft.FontWeight.BOLD, size=10, color=c)) for t, c in cols_stock],
            rows=[],
        )
        tabla_consultador_avanzado = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=32,
            data_row_max_height=38,
            column_spacing=15,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[ft.DataColumn(ft.Text(t, weight=ft.FontWeight.BOLD, size=10, color=c)) for t, c in cols_stock],
            rows=[],
        )
        tabla_reabastecimiento = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=32,
            data_row_max_height=38,
            column_spacing=16,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("PRIORIDAD", weight=ft.FontWeight.BOLD, size=10, color="#F87171")),
                ft.DataColumn(ft.Text("SKU", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("DESCRIPCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("STOCK NIVEL 1", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_AMBER)),
                ft.DataColumn(ft.Text("STOCK RESERVA (N2+)", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("LPN SUGERIDO (FEFO)", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("DESDE UBICACIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIÓN RF", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
            ],
            rows=[],
        )

        cont_tabla_monitor = envolver_tabla_scroll(tabla_monitor_zona, 285)
        cont_tabla_consultador = envolver_tabla_scroll(tabla_consultador_avanzado, 340)
        cont_tabla_reapro = envolver_tabla_scroll(tabla_reabastecimiento, 320)
        contenedor_gemelo_visual = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)

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
            }

        def sincronizar_datos_supabase():
            nonlocal lpns_en_anden, stock_en_racks, mapa_descripciones_sku
            try:
                filas_mae = cargar_tabla_paginada("maestra_sku", 3000)
                mapa_descripciones_sku = {
                    str(m.get("sku", "")).strip().upper(): str(m.get("descripcion") or "")
                    for m in filas_mae
                    if m.get("sku")
                }
            except Exception:
                mapa_descripciones_sku = {}

            mapa_rec_por_lpn = {}
            filas_recepcion = []
            try:
                filas_recepcion = cargar_tabla_paginada("registro_recepcion", 4000)
                for r in filas_recepcion:
                    lpn_k = str(r.get("lpn") or "").strip().upper()
                    if lpn_k:
                        mapa_rec_por_lpn[lpn_k] = r
            except Exception:
                filas_recepcion = []

            ubicados_map = {}
            lpns_ubicados_set = set()

            for nom_tabla in ("bodega_ubicaciones", "inventario_ubicaciones", "stock_ubicaciones", "ubicaciones_stock"):
                try:
                    filas_u = cargar_tabla_paginada(nom_tabla, 4000)
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
                            row_u.get("unidades")
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
                        clave_u = (ubi_cod, lpn_u or sku_f)
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

        # --- 8. COMPONENTES DINÁMICOS (BOTONES DE RACKS Y FILAS DE TABLA) ---
        def crear_fila_tabla_stock(it: dict) -> ft.DataRow:
            es_anden = it["rack"] == "RECEPCION"
            badge_niv = (
                crear_badge_estado("ANDÉN RECEPCIÓN", "#92400E", "#FEF3C7")
                if es_anden
                else (
                    crear_badge_estado("PICKING NIVEL 1", "#065F46", "#D1FAE5")
                    if it["nivel_num"] <= 1
                    else crear_badge_estado("RESERVA ALTURA", "#1E3A8A", "#DBEAFE")
                )
            )
            qa_val = it["qa"]
            badge_qa = (
                crear_badge_estado("APROBADO", "#065F46", "#D1FAE5")
                if qa_val == "APROBADO"
                else (
                    crear_badge_estado("CUARENTENA", "#92400E", "#FEF3C7")
                    if qa_val == "CUARENTENA"
                    else crear_badge_estado("RECHAZADO", "#991B1B", "#FEE2E2")
                )
            )
            lpn_c = it["lpn"]
            return ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(it["ubicacion"], weight=ft.FontWeight.BOLD, size=11, color=ACCENT_AMBER if es_anden else ACCENT_CYAN)),
                    ft.DataCell(ft.Text(it["rack"], weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                    ft.DataCell(badge_niv),
                    ft.DataCell(ft.Text(lpn_c, weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                    ft.DataCell(ft.Text(it["sku"], weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                    ft.DataCell(ft.Text(it["descripcion"][:28], size=11, color=TEXT_MUTED)),
                    ft.DataCell(ft.Text(str(it["unidades"]), weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                    ft.DataCell(ft.Text(it["lote"], size=11, color=TEXT_WHITE)),
                    ft.DataCell(ft.Text(it["vencimiento"], size=11, color=TEXT_WHITE)),
                    ft.DataCell(badge_qa),
                    ft.DataCell(
                        boton_primario(
                            "LPN 15x10",
                            ft.Icons.PRINT_OUTLINED,
                            lambda ev, cod=lpn_c: reimprimir_desde_fila(cod),
                            ACCENT_TEAL,
                            height_val=26,
                        )
                    ),
                ]
            )

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
                os.makedirs("reportes_recepcion", exist_ok=True)
                df_exp = pd.DataFrame(
                    [
                        {
                            "Zona / Rack": x["rack"],
                            "Ubicacion": x["ubicacion"],
                            "Nivel": x["zona_nivel"],
                            "LPN": x["lpn"],
                            "SKU": x["sku"],
                            "Descripcion": x["descripcion"],
                            "Unidades": x["unidades"],
                            "Lote": x["lote"],
                            "Vencimiento": x["vencimiento"],
                            "QA": x["qa"],
                        }
                        for x in universo
                    ]
                )
                ruta_xlsx = os.path.join(
                    "reportes_recepcion",
                    f"Stock_Ubicaciones_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                )
                df_exp.to_excel(ruta_xlsx, index=False)
                notificar(f"Excel exportado: {ruta_xlsx}", "#047857")
                descargar_o_abrir_archivo(self.page, ruta_xlsx)
            except Exception as ex:
                notificar(f"Error exportando Excel: {ex}", "#B91C1C")

        txt_cons_buscar.on_change = ejecutar_filtro_consultador
        dd_cons_zona.on_change = ejecutar_filtro_consultador
        dd_cons_nivel.on_change = ejecutar_filtro_consultador
        dd_cons_qa.on_change = ejecutar_filtro_consultador

        def renderizar_todo_el_modulo():
            racks_base = ["RACK A", "RACK B", "RACK C", "RACK D"]
            for rk in sorted({x["rack"] for x in stock_en_racks if x["rack"].startswith("RACK ")}):
                if rk not in racks_base:
                    racks_base.append(rk)

            dd_cons_zona.options = [
                opt_w("TODOS", "TODO EL CD (RACKS + ANDÉN)"),
                opt_w("SOLO_RACKS", "SOLO EN RACKS"),
                opt_w("RECEPCION", "SOLO EN RECEPCIÓN"),
            ] + [opt_w(rk, rk) for rk in racks_base]

            fila_botones_zonas.controls.clear()
            fila_barras_racks.controls.clear()

            def sel_zona(nueva_z: str):
                nonlocal zona_seleccionada
                zona_seleccionada = nueva_z
                renderizar_todo_el_modulo()

            # Botón Recepción y Botón Todos los Racks
            fila_botones_zonas.controls.append(
                crear_boton_zona_rack(
                    "RECEPCION",
                    "RECEPCIÓN (ANDÉN)",
                    ft.Icons.MOVE_TO_INBOX_ROUNDED,
                    len(lpns_en_anden),
                    sum(x["unidades"] for x in lpns_en_anden),
                    len({x["sku"] for x in lpns_en_anden}),
                    ACCENT_AMBER,
                    lambda e: sel_zona("RECEPCION"),
                )
            )
            fila_botones_zonas.controls.append(
                crear_boton_zona_rack(
                    "TODOS_RACKS",
                    "TODOS LOS RACKS",
                    ft.Icons.WAREHOUSE_OUTLINED,
                    len(stock_en_racks),
                    sum(x["unidades"] for x in stock_en_racks),
                    len({x["sku"] for x in stock_en_racks}),
                    ACCENT_CYAN,
                    lambda e: sel_zona("TODOS_RACKS"),
                )
            )

            colores_rk = [ACCENT_GREEN, ACCENT_BLUE, ACCENT_PURPLE, "#EC4899", "#14B8A6", "#F97316"]
            datos_graf = [("RECEPCIÓN", len(lpns_en_anden), ACCENT_AMBER, "RECEPCION")]

            for i_r, nom_rk in enumerate(racks_base):
                items_r = [x for x in stock_en_racks if x["rack"] == nom_rk]
                col_r = colores_rk[i_r % len(colores_rk)]
                fila_botones_zonas.controls.append(
                    crear_boton_zona_rack(
                        nom_rk,
                        nom_rk,
                        ft.Icons.DNS_OUTLINED,
                        len(items_r),
                        sum(x["unidades"] for x in items_r),
                        len({x["sku"] for x in items_r}),
                        col_r,
                        lambda e, rk_s=nom_rk: sel_zona(rk_s),
                    )
                )
                datos_graf.append((nom_rk, len(items_r), col_r, nom_rk))

            max_g = max([d[1] for d in datos_graf] + [1])
            for et_g, cnt_g, col_g, cl_g in datos_graf:
                alto_b = max(10, int((cnt_g / max_g) * 95)) if cnt_g > 0 else 5
                fila_barras_racks.controls.append(
                    ft.Column(
                        [
                            ft.Text(str(cnt_g), size=10, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            ft.Container(
                                width=44,
                                height=95,
                                bgcolor="#141A1C",
                                border_radius=4,
                                alignment=ft.Alignment.BOTTOM_CENTER,
                                ink=True,
                                on_click=lambda e, c=cl_g: sel_zona(c),
                                content=ft.Container(width=44, height=alto_b, bgcolor=col_g, border_radius=4),
                            ),
                            ft.Text(
                                et_g,
                                size=10,
                                weight=ft.FontWeight.BOLD,
                                color=ACCENT_CYAN if zona_seleccionada == cl_g else TEXT_MUTED,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=3,
                    )
                )

            if zona_seleccionada == "RECEPCION":
                items_vista = lpns_en_anden
                lbl_titulo_tabla_monitor.value = f"📥 LPNs EN RECEPCIÓN PENDIENTES DE UBICAR EN APP MÓVIL RF ({len(items_vista)} LPNs)"
                lbl_titulo_tabla_monitor.color = ACCENT_AMBER
            elif zona_seleccionada == "TODOS_RACKS":
                items_vista = stock_en_racks
                lbl_titulo_tabla_monitor.value = f"🏢 MAPA GENERAL DE STOCK EN TODOS LOS RACKS ({len(items_vista)} LPNs)"
                lbl_titulo_tabla_monitor.color = ACCENT_CYAN
            else:
                items_vista = [x for x in stock_en_racks if x["rack"] == zona_seleccionada]
                lbl_titulo_tabla_monitor.value = f"🗄️ PALLETS (LPNs) ALMACENADOS EN {zona_seleccionada} ({len(items_vista)} LPNs)"
                lbl_titulo_tabla_monitor.color = ACCENT_GREEN

            lbl_dig_anden.value = str(len(lpns_en_anden))
            lbl_dig_racks.value = str(len(stock_en_racks))
            lbl_dig_picking_n1.value = str(sum(1 for x in stock_en_racks if x["nivel_num"] <= 1))
            lbl_dig_reserva_alt.value = str(sum(1 for x in stock_en_racks if x["nivel_num"] > 1))

            lbl_dig_unid_zona.value = str(sum(x["unidades"] for x in items_vista))
            lbl_dig_skus_zona.value = str(len({x["sku"] for x in items_vista}))
            lbl_dig_pos_ocup.value = str(len({x["ubicacion"] for x in items_vista}))

            tabla_monitor_zona.rows = [crear_fila_tabla_stock(it) for it in items_vista[:200]]

            # Alertas de Reabastecimiento (Reserva N2+ -> Picking N1)
            por_sku = {}
            for x in stock_en_racks:
                sk = x["sku"]
                if sk not in por_sku:
                    por_sku[sk] = {"n1": 0, "res": 0, "cands": []}
                if x["nivel_num"] <= 1:
                    por_sku[sk]["n1"] += x["unidades"]
                else:
                    por_sku[sk]["res"] += x["unidades"]
                    por_sku[sk]["cands"].append(x)

            tabla_reabastecimiento.rows.clear()
            alertas_cnt = 0
            for sk, d_n in sorted(por_sku.items(), key=lambda i: i[1]["n1"]):
                if d_n["res"] > 0 and d_n["n1"] < 200:
                    alertas_cnt += 1
                    cand = d_n["cands"][0]
                    crit = d_n["n1"] == 0
                    tabla_reabastecimiento.rows.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(
                                    crear_badge_estado(
                                        "QUIEBRE N1" if crit else "REABASTECER",
                                        "#991B1B" if crit else "#92400E",
                                        "#FEE2E2" if crit else "#FEF3C7",
                                    )
                                ),
                                ft.DataCell(ft.Text(sk, weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(mapa_descripciones_sku.get(sk, "-")[:30], size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"{d_n['n1']} UN", weight=ft.FontWeight.BOLD, size=11, color="#F87171" if crit else ACCENT_AMBER)),
                                ft.DataCell(ft.Text(f"{d_n['res']} UN", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                                ft.DataCell(ft.Text(cand["lpn"], weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(cand["ubicacion"], weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text("📱 Bajar con App RF", size=10, color=TEXT_MUTED)),
                            ]
                        )
                    )
            lbl_dig_alertas_reapro.value = str(alertas_cnt)

            # Gemelo Digital Visual
            contenedor_gemelo_visual.controls.clear()
            for nom_rk in racks_base:
                items_r = [x for x in stock_en_racks if x["rack"] == nom_rk]
                chips = [
                    ft.Container(
                        width=124,
                        padding=8,
                        bgcolor="#064E3B" if p["nivel_num"] <= 1 else "#1E3A8A",
                        border_radius=6,
                        border=ft.Border.all(1, "#34D399" if p["nivel_num"] <= 1 else ACCENT_CYAN),
                        content=ft.Column(
                            [
                                ft.Text(p["ubicacion"], size=11, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                                ft.Text(p["lpn"], size=10, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
                                ft.Text(f"{p['sku']} • {p['unidades']} UN", size=9, color=TEXT_WHITE),
                            ],
                            spacing=2,
                        ),
                    )
                    for p in items_r[:36]
                ] or [ft.Text(f"Sin posiciones ocupadas en {nom_rk}", size=11, color=TEXT_MUTED)]
                contenedor_gemelo_visual.controls.append(
                    tarjeta_dark(
                        ft.Column(
                            [
                                ft.Text(
                                    f"MAPA DE POSICIONES — {nom_rk} ({len(items_r)} LPNs)",
                                    size=12,
                                    weight=ft.FontWeight.BOLD,
                                    color=TEXT_WHITE,
                                ),
                                ft.Divider(color=BORDER_COLOR, height=4),
                                ft.Row(chips, wrap=True, spacing=8, run_spacing=8),
                            ],
                            spacing=6,
                        )
                    )
                )

            ejecutar_filtro_consultador()

        def cargar_inventario_ubicaciones(e=None):
            sincronizar_datos_supabase()
            renderizar_todo_el_modulo()

        # --- 9. VISTAS DEL MÓDULO ---
        panel_relojes_izquierdo = tarjeta_dark(
            ft.Column(
                [
                    ft.Text("Distribución global de pallets (LPNs) en Bodega", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Row(
                        [
                            crear_caja_digital(lbl_dig_anden, "En Recepción", ACCENT_AMBER, 88),
                            crear_caja_digital(lbl_dig_racks, "En Racks", ACCENT_CYAN, 88),
                            crear_caja_digital(lbl_dig_picking_n1, "Picking N1", ACCENT_GREEN, 88),
                            crear_caja_digital(lbl_dig_reserva_alt, "Reserva N2+", ACCENT_PURPLE, 88),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=8),
                    ft.Text("Indicadores de la Zona / Rack seleccionado", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Row(
                        [
                            crear_caja_digital(lbl_dig_unid_zona, "Unid. Zona", ACCENT_TEAL, 88),
                            crear_caja_digital(lbl_dig_skus_zona, "SKUs Zona", ACCENT_BLUE, 88),
                            crear_caja_digital(lbl_dig_pos_ocup, "Ubic. Ocup.", "#10B981", 88),
                            crear_caja_digital(lbl_dig_alertas_reapro, "Alertas N1", "#EF4444", 88),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                spacing=8,
            ),
            width_val=425,
        )

        panel_grafico_derecho = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Ocupación de LPNs: Recepción vs. Racks (A, B, C, D...)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            ft.Text("📱 Putaway exclusivo vía App Móvil RF", size=11, color=ACCENT_CYAN, weight=ft.FontWeight.BOLD),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=6),
                    ft.Container(
                        height=150,
                        padding=10,
                        bgcolor="#181E20",
                        border_radius=6,
                        alignment=ft.Alignment.BOTTOM_LEFT,
                        content=fila_barras_racks,
                    ),
                ],
                spacing=8,
            ),
            expand_val=True,
        )

        vista_1_monitor_racks = ft.Column(
            [
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Text(
                                "SELECCIONE UN BOTÓN DE ZONA O RACK PARA VER SUS LPNs EN TIEMPO REAL",
                                size=12,
                                weight=ft.FontWeight.BOLD,
                                color=TEXT_WHITE,
                            ),
                            ft.Divider(color=BORDER_COLOR, height=4),
                            fila_botones_zonas,
                        ],
                        spacing=8,
                    )
                ),
                ft.Row([panel_relojes_izquierdo, panel_grafico_derecho], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Column([lbl_titulo_tabla_monitor, lbl_subtitulo_tabla_monitor], spacing=2),
                                    ft.Row(
                                        [
                                            boton_primario(
                                                "IR A ZONA CONSULTADOR",
                                                ft.Icons.MANAGE_SEARCH_ROUNDED,
                                                lambda e: self.sel_sub_put(2),
                                                ACCENT_BLUE,
                                                height_val=30,
                                            ),
                                            boton_primario(
                                                "EXPORTAR EXCEL",
                                                ft.Icons.TABLE_VIEW_OUTLINED,
                                                exportar_excel_consultador,
                                                ACCENT_TEAL,
                                                height_val=30,
                                            ),
                                        ],
                                        spacing=8,
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                wrap=True,
                            ),
                            ft.Divider(color=BORDER_COLOR, height=1),
                            cont_tabla_monitor,
                        ],
                        spacing=8,
                    )
                ),
            ],
            spacing=10,
        )

        vista_2_reabastecimiento = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                "ALERTAS DE REABASTECIMIENTO (RESERVA ALTURA -> NIVEL 1 PICKING)",
                                size=13,
                                weight=ft.FontWeight.BOLD,
                                color=TEXT_WHITE,
                            ),
                            boton_primario(
                                "REFRESCAR ALERTAS",
                                ft.Icons.REFRESH_ROUNDED,
                                cargar_inventario_ubicaciones,
                                ACCENT_TEAL,
                                height_val=30,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=1),
                    cont_tabla_reapro,
                ],
                spacing=8,
            )
        )

        vista_3_consultador_aparte = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                "🔍 ZONA CONSULTADOR AVANZADO DE STOCK, UBICACIONES Y LPNs",
                                size=14,
                                weight=ft.FontWeight.W_900,
                                color=TEXT_WHITE,
                            ),
                            ft.Row(
                                [
                                    boton_primario(
                                        "LIMPIAR FILTROS",
                                        ft.Icons.FILTER_ALT_OFF_OUTLINED,
                                        limpiar_filtros_consultador,
                                        "#475569",
                                        height_val=30,
                                    ),
                                    boton_primario(
                                        "EXPORTAR EXCEL (.XLSX)",
                                        ft.Icons.DOWNLOAD_ROUNDED,
                                        exportar_excel_consultador,
                                        "#047857",
                                        height_val=30,
                                    ),
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=4),
                    ft.Row([txt_cons_buscar, dd_cons_zona, dd_cons_nivel, dd_cons_qa], spacing=8, wrap=True),
                    ft.Container(
                        padding=ft.Padding.symmetric(horizontal=14, vertical=8),
                        bgcolor="#181E20",
                        border_radius=6,
                        border=ft.Border.all(1, BORDER_COLOR),
                        content=ft.Row(
                            [
                                ft.Text("RESUMEN DE BÚSQUEDA:", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
                                lbl_cons_res_lpns,
                                lbl_cons_res_unid,
                                lbl_cons_res_skus,
                                lbl_cons_res_ubic,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            wrap=True,
                        ),
                    ),
                    cont_tabla_consultador,
                ],
                spacing=10,
            )
        )

        vista_4_gemelo_digital = ft.Column([contenedor_gemelo_visual], spacing=10)
        contenedor_subvista_putaway = ft.Container(content=vista_1_monitor_racks)

        def cambiar_subvista_interna(idx: int):
            contenedor_subvista_putaway.content = [
                vista_1_monitor_racks,
                vista_2_reabastecimiento,
                vista_3_consultador_aparte,
                vista_4_gemelo_digital,
            ][idx]
            page.update()

        barra_titulo_monitor = ft.Container(
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            bgcolor="#222A2C",
            border_radius=8,
            border=ft.Border.all(1, BORDER_COLOR),
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.ACCOUNT_TREE_OUTLINED, color=ACCENT_CYAN, size=22),
                            ft.Text(
                                "TORRE DE ALMACENAMIENTO (PUTAWAY MÓVIL RF) & MAPA DE RACKS",
                                size=15,
                                weight=ft.FontWeight.W_900,
                                color=TEXT_WHITE,
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Row(
                        [
                            boton_primario("1. MONITOR RACKS", ft.Icons.DOMAIN_OUTLINED, lambda e: cambiar_subvista_interna(0), ACCENT_TEAL, height_val=30),
                            boton_primario("2. ZONA CONSULTADOR", ft.Icons.MANAGE_SEARCH_ROUNDED, lambda e: cambiar_subvista_interna(2), ACCENT_BLUE, height_val=30),
                            boton_primario("3. REABASTECIMIENTO N1", ft.Icons.ARROW_DOWNWARD_ROUNDED, lambda e: cambiar_subvista_interna(1), "#D97706", height_val=30),
                            boton_primario("4. GEMELO DIGITAL", ft.Icons.VIEW_IN_AR_ROUNDED, lambda e: cambiar_subvista_interna(3), ACCENT_PURPLE, height_val=30),
                            ft.IconButton(
                                icon=ft.Icons.SYNC_ROUNDED,
                                icon_color=ACCENT_CYAN,
                                tooltip="Sincronizar con App RF",
                                on_click=cargar_inventario_ubicaciones,
                            ),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                wrap=True,
            ),
        )

        col_putaway = ft.Column([barra_titulo_monitor, contenedor_subvista_putaway], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

        self.vista = ft.Container(padding=14, bgcolor=BG_MODULO, content=col_putaway, expand=True)
        self.contenedor = contenedor_subvista_putaway
        self.cargar_inventario_ubicaciones_func = cargar_inventario_ubicaciones
        self.cambiar_subvista_interna_func = cambiar_subvista_interna

    def cargar_inventario_ubicaciones(self, e=None):
        self.cargar_inventario_ubicaciones_func(e)

    def sel_sub_put(self, idx: int):
        self.cargar_inventario_ubicaciones_func()
        self.cambiar_subvista_interna_func(idx)