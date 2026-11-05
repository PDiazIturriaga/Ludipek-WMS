import os
import json
import urllib.request
from datetime import datetime
import pandas as pd
import flet as ft
from dependencias import *


class PickingModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables

        # --- 1. CONSTANTES DE DISEÑO OSCURO (ESTILO MONITOR INDUSTRIAL) ---
        BG_MODULO = "#1B2122"
        BG_CARD = "#262E30"
        BG_INPUT = "#1D2426"
        BG_DIGITAL = "#121718"
        BORDER_COLOR = "#3B484B"
        ACCENT_TEAL = "#527976"
        ACCENT_CYAN = "#38BDF8"
        ACCENT_BLUE = "#0284C7"
        ACCENT_PURPLE = "#8B5CF6"
        TEXT_WHITE = "#FFFFFF"
        TEXT_MUTED = "#94A3B8"

        # --- 2. VARIABLES DE ESTADO ---
        olas_extraidas_ns = []        # Revisión de vistas, con proceso de ov
        checks_liberacion = {}        # {ov_key: ft.Checkbox}
        registros_packing_db = []     # Lista de OVs en las estaciones de Packing
        registros_locales_mem = []    # Respaldo en memoria para visualización inmediata
        filtro_corte_activo = "TODOS"
        esquemas_tablas_sb = {}       # {nombre_tabla: [columnas]}
        tablas_destino_olas = []      # Tablas reales detectadas en Supabase para Olas/Packing

        def boton_primario(texto: str, icono, on_click, color_bg: str, height_val: int = 34, width_val=None):
            def animar_hover(e):
                e.control.opacity = 0.82 if e.data == "true" else 1.0
                e.control.scale = 1.02 if e.data == "true" else 1.0
                e.control.update()

            return ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(icono, color=TEXT_WHITE, size=15),
                        ft.Text(texto, size=11, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ],
                    spacing=6,
                    alignment=ft.MainAxisAlignment.CENTER,
                    tight=True,
                ),
                bgcolor=color_bg,
                padding=ft.Padding.symmetric(horizontal=12, vertical=0),
                height=height_val,
                width=width_val,
                border_radius=6,
                ink=True,
                on_click=on_click,
                on_hover=animar_hover,
                scale=1.0,
                animate_scale=ft.Animation(120, ft.AnimationCurve.EASE_OUT),
                animate_opacity=120,
            )

        # --- 3. FUNCIONES AUXILIARES DE UI ---
        def notificar(texto: str, color: str = "#0284C7"):
            from dependencias import notificar_global
            notificar_global(self.page, texto, color)

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

        def crear_caja_digital(txt_control: ft.Text, etiqueta_inf: str, color_borde: str = "#6366F1", ancho: int = 86, on_click=None):
            return ft.Column(
                [
                    ft.Container(
                        width=ancho,
                        height=60,
                        bgcolor=BG_DIGITAL,
                        border_radius=6,
                        border=ft.Border.all(1.5, color_borde),
                        alignment=ft.Alignment.CENTER,
                        shadow=ft.BoxShadow(blur_radius=6, color="#33000000"),
                        ink=bool(on_click),
                        on_click=on_click,
                        tooltip=f"Filtrar / Ver {etiqueta_inf}" if on_click else None,
                        content=txt_control,
                    ),
                    ft.Text(etiqueta_inf, size=10, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            )

        # --- 4. CLASIFICADOR INTELIGENTE DE CORTE HORARIO (09:00, 10:00, 12:00, 13:00) ---
        def clasificar_corte_horario(valor_fecha_hora, corte_forzado: str = None) -> str:
            if corte_forzado and corte_forzado in ("09:00", "10:00", "12:00", "13:00", ">13:00"):
                return corte_forzado
            texto = str(valor_fecha_hora or "").strip()
            if texto in ("09:00", "10:00", "12:00", "13:00", ">13:00"):
                return texto

            hora_float = None
            if texto and texto not in ("None", "null", ""):
                try:
                    dt = datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone()
                    hora_float = dt.hour + (dt.minute / 60.0)
                except Exception:
                    for parte in texto.replace("T", " ").split():
                        if ":" in parte and len(parte) >= 4:
                            try:
                                hh, mm = parte.split(":")[:2]
                                hora_float = int(hh) + (int(mm) / 60.0)
                                break
                            except Exception:
                                pass

            if hora_float is None:
                ahora = datetime.now()
                hora_float = ahora.hour + (ahora.minute / 60.0)

            if hora_float <= 9.05:
                return "09:00"
            elif hora_float <= 10.05:
                return "10:00"
            elif hora_float <= 12.05:
                return "12:00"
            elif hora_float <= 13.05:
                return "13:00"
            else:
                return ">13:00"

        def obtener_tip_corte_actual() -> tuple:
            ahora = datetime.now()
            hm = ahora.hour + (ahora.minute / 60.0)
            if hm < 9.0:
                return ("PRÓXIMO CORTE: 09:00 HRS (Arranque AM)", "#38BDF8")
            elif hm < 10.0:
                return ("CORTE 09:00 CERRADO • PRÓXIMO CORTE: 10:00 HRS", "#34D399")
            elif hm < 12.0:
                return ("CORTE 10:00 CERRADO • PRÓXIMO CORTE: 12:00 HRS (Mediodía)", "#FBBF24")
            elif hm < 13.0:
                return ("CORTE 12:00 CERRADO • ÚLTIMO CORTE DEL DÍA: 13:00 HRS", "#F97316")
            else:
                return ("CORTES 09•10•12•13 HRS COMPLETADOS • MODO POST-CORTE (>13:00)", "#A78BFA")

        # --- 5. CONTROLES VISUALES Y CONTADORES DIGITALES ---
        hoy_str = datetime.now().strftime("%Y-%m-%d")
        txt_fecha_desde = texto_dark(label="Fecha Desde (YYYY-MM-DD)", value=hoy_str, width=155)
        txt_fecha_hasta = texto_dark(label="Fecha Hasta (YYYY-MM-DD)", value=hoy_str, width=155)

        dd_corte_asignar = dropdown_dark(
            label="Corte al Liberar Ola",
            width=165,
            value="AUTO",
            options=[
                opt_w("AUTO", "AUTO (Por Hora OV)"),
                opt_w("09:00", "Corte 09:00 hrs"),
                opt_w("10:00", "Corte 10:00 hrs"),
                opt_w("12:00", "Corte 12:00 hrs"),
                opt_w("13:00", "Corte 13:00 hrs"),
                opt_w(">13:00", "Extra (>13:00 hrs)"),
            ],
        )

        dd_filtro_corte = dropdown_dark(
            label="Filtrar Monitor por Corte",
            width=185,
            value="TODOS",
            options=[
                opt_w("TODOS", "TODOS LOS CORTES"),
                opt_w("09:00", "⏱️ Corte 09:00 hrs"),
                opt_w("10:00", "⏱️ Corte 10:00 hrs"),
                opt_w("12:00", "⏱️ Corte 12:00 hrs"),
                opt_w("13:00", "⏱️ Corte 13:00 hrs"),
                opt_w(">13:00", "⏱️ Post 13:00 hrs"),
            ],
        )

        txt_msg_tip, color_tip_ini = obtener_tip_corte_actual()
        lbl_tip_corte = ft.Text(txt_msg_tip, size=11, weight=ft.FontWeight.BOLD, color=color_tip_ini)

        txt_estado_erp = ft.Text(
            f"Estado ERP: {'Módulo conexion_erp activo.' if NETSUITE_CONECTADO else 'Modo Cloud Supabase activo.'}",
            size=11,
            color="#34D399" if NETSUITE_CONECTADO else "#FBBF24",
        )

        lbl_corte_09 = ft.Text("00", size=24, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_corte_10 = ft.Text("00", size=24, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_corte_12 = ft.Text("00", size=24, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_corte_13 = ft.Text("00", size=24, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")

        lbl_kpi_total_ovs = ft.Text("0", size=18, weight=ft.FontWeight.W_900, color=TEXT_WHITE, font_family="Consolas")
        lbl_kpi_ov_normal = ft.Text("0", size=18, weight=ft.FontWeight.W_900, color="#38BDF8", font_family="Consolas")
        lbl_kpi_ov_farma = ft.Text("0", size=18, weight=ft.FontWeight.W_900, color="#FBBF24", font_family="Consolas")
        lbl_kpi_avance_pack = ft.Text("0%", size=18, weight=ft.FontWeight.W_900, color="#34D399", font_family="Consolas")

        fila_barras_cortes = ft.Row(
            spacing=16,
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
            vertical_alignment=ft.CrossAxisAlignment.END,
        )
        col_detalle_ovs_por_corte = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

        # --- 6. TABLAS EN MODO OSCURO ---
        tabla_previsualizacion_ns = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=30,
            data_row_max_height=36,
            column_spacing=16,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("LIBERAR", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("ORDEN DE VENTA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("CORTE HORARIO", weight=ft.FontWeight.BOLD, size=10, color="#A78BFA")),
                ft.DataColumn(ft.Text("CANAL / ZONA (CLIC CAMBIAR)", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("CLIENTE", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("LÍNEAS", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("UNIDADES", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("DETALLE", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        tabla_packing_normal = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=32,
            data_row_max_height=38,
            column_spacing=14,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("OV ESTÁNDAR", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("CORTE", weight=ft.FontWeight.BOLD, size=10, color="#A78BFA")),
                ft.DataColumn(ft.Text("CLIENTE", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ESTADO ACTUAL", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        tabla_packing_farmacia = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=32,
            data_row_max_height=38,
            column_spacing=14,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("OV FARMACIA (-FA)", weight=ft.FontWeight.BOLD, size=10, color="#FBBF24")),
                ft.DataColumn(ft.Text("CORTE", weight=ft.FontWeight.BOLD, size=10, color="#A78BFA")),
                ft.DataColumn(ft.Text("CLIENTE", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ESTADO SANITARIO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        cont_tabla_prev_ns = envolver_tabla_scroll(tabla_previsualizacion_ns, 195)
        cont_tabla_pack_norm = envolver_tabla_scroll(tabla_packing_normal, 235)
        cont_tabla_pack_farm = envolver_tabla_scroll(tabla_packing_farmacia, 235)

        # --- 7. CONEXIÓN EXACTA CON SUPABASE (netsuite_ordenes_venta, netsuite_detalle_ov, wms_packing_lists_fa) ---
        def descubrir_tablas_olas_supabase() -> list:
            nonlocal tablas_destino_olas
            tablas_destino_olas = [
                "netsuite_ordenes_venta",
                "wms_packing_lists_fa",
                "v_torre_control_ov_resumen",
            ]
            return tablas_destino_olas

        def obtener_columnas_reales_tabla(nombre_tabla: str) -> list:
            if nombre_tabla in esquemas_tablas_sb and esquemas_tablas_sb[nombre_tabla]:
                return esquemas_tablas_sb[nombre_tabla]
            try:
                sb_url = (
                    getattr(supabase, "supabase_url", None)
                    or getattr(supabase, "rest_url", "").replace("/rest/v1", "")
                    or globals().get("SUPABASE_URL")
                    or os.environ.get("SUPABASE_URL", "")
                )
                sb_key = (
                    getattr(supabase, "supabase_key", None)
                    or globals().get("SUPABASE_KEY")
                    or os.environ.get("SUPABASE_KEY", "")
                )
                if sb_url and sb_key:
                    req = urllib.request.Request(
                        f"{str(sb_url).rstrip('/')}/rest/v1/",
                        headers={"apikey": str(sb_key), "Authorization": f"Bearer {sb_key}"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        spec = json.loads(resp.read().decode("utf-8"))
                        defs = spec.get("definitions", {})
                        for t_name, t_info in defs.items():
                            esquemas_tablas_sb[t_name] = list((t_info.get("properties") or {}).keys())
            except Exception:
                pass
            return esquemas_tablas_sb.get(nombre_tabla, [])

        def insertar_seguro_supabase(nombre_tabla: str, payload_candidato: dict, col_unico: str = "numero_ov"):
            import re
            cols_reales = obtener_columnas_reales_tabla(nombre_tabla)
            if cols_reales:
                mapa_cols = {c.lower(): c for c in cols_reales if c.lower() != "id"}
                datos = {
                    mapa_cols[k.lower()]: v
                    for k, v in payload_candidato.items()
                    if k.lower() in mapa_cols and v is not None
                }
            else:
                datos = {k: v for k, v in payload_candidato.items() if k.lower() != "id" and v is not None}

            for _ in range(25):
                if not datos:
                    break
                try:
                    res = supabase.table(nombre_tabla).insert(datos).execute()
                    return res.data[0] if res.data else datos
                except Exception as ex:
                    err_txt = str(ex)
                    m_col = re.search(r"Could not find the '([^']+)' column", err_txt)
                    if not m_col:
                        m_col = re.search(r'column "([^"]+)" of relation', err_txt)
                    if m_col:
                        datos.pop(m_col.group(1), None)
                        continue

                    if "23505" in err_txt or "duplicate key" in err_txt.lower():
                        for c_up in (col_unico, "numero_ov", "id_externo_ns"):
                            if c_up and c_up in datos:
                                try:
                                    res_u = supabase.table(nombre_tabla).update(datos).eq(c_up, datos[c_up]).execute()
                                    if res_u.data:
                                        return res_u.data[0]
                                except Exception:
                                    pass
                        return datos

                    print(f"[ERROR SUPABASE {nombre_tabla}]: {err_txt} | Payload: {datos}")
                    break
            return None

        def detectar_es_farmacia_texto(*textos) -> bool:
            for t in textos:
                s = str(t or "").strip().upper()
                if not s:
                    continue
                if (
                    "-FA" in s
                    or s.endswith("FA")
                    or "BOEHRINGER" in s
                    or "PICK-FARM" in s
                    or "FARMACIA" in s
                ):
                    return True
            return False

        def extraer_campos_registro_ola(r: dict, mapa_clientes_ns: dict = None) -> dict:
            ov_val = str(
                r.get("numero_ov")
                or r.get("orden_venta")
                or r.get("ov")
                or r.get("id_externo_ns")
                or ""
            ).strip().upper().replace("OV ", "").strip()

            if not ov_val or ov_val in ("NONE", "NULL", "-"):
                return None

            cli_val = str(
                r.get("cliente_nombre")
                or r.get("cliente")
                or r.get("nombre_cliente")
                or r.get("razon_social")
                or ""
            ).strip()

            ov_limpia = ov_val.replace("-FA", "").strip()
            if cli_val.upper() == "CLIENTE B2B" or (ov_limpia.isdigit() and len(ov_limpia) <= 4 and not r.get("numero_ov")):
                return None

            if not cli_val or cli_val.upper() in ("NONE", "NULL", "-"):
                if mapa_clientes_ns:
                    cli_val = mapa_clientes_ns.get(ov_val) or mapa_clientes_ns.get(ov_limpia) or "CLIENTE REGISTRADO"
                else:
                    cli_val = "CLIENTE REGISTRADO"

            est_val = str(
                r.get("estado_ns")
                or r.get("estado_wms")
                or r.get("estado")
                or r.get("estado_packing")
                or r.get("estado_picking")
                or r.get("estado_sanitario")
                or "PENDIENTE_PICKING"
            ).strip().upper()

            canal_val = str(
                r.get("canal_venta")
                or r.get("tipo_ola")
                or r.get("canal")
                or ""
            ).strip().upper()

            es_fa = (
                bool(r.get("es_farmacia"))
                or detectar_es_farmacia_texto(ov_val, canal_val, r.get("sku"), r.get("descripcion"))
            )
            if es_fa and not ov_val.endswith("-FA"):
                ov_val = f"{ov_val}-FA"

            ts_val = (
                r.get("corte_horario")
                or r.get("hora_corte")
                or r.get("corte")
                or r.get("fecha_emision_ns")
                or r.get("created_at")
            )
            corte_str = clasificar_corte_horario(ts_val) if ts_val else clasificar_corte_horario(None)

            try:
                unid_val = int(float(r.get("unidades") or r.get("unidades_totales") or r.get("total_unidades") or r.get("cantidad") or 1))
            except Exception:
                unid_val = 1

            return {
                "raw": r,
                "id": r.get("id"),
                "ov": ov_val,
                "cliente": cli_val,
                "estado": est_val,
                "es_farmacia": es_fa,
                "corte": corte_str,
                "unidades": unid_val,
                "unidades_pickeadas": int(float(r.get("unidades_pickeadas") or r.get("cantidad_pickeada") or 0)),
                "lineas_detalle": [],
                "tabla_origen": r.get("_tabla_origen") or "netsuite_ordenes_venta",
            }

        def recargar_datos_supabase():
            nonlocal registros_packing_db
            agrupado_por_ov = {}

            # 1. Cargar catálogo de maestra_sku (Descripción y EAN / GTIN Base)
            mapa_maestra_sku = {}
            try:
                res_m = supabase.table("maestra_sku").select("*").limit(4000).execute()
                for m in (res_m.data or []):
                    s_k = str(m.get("sku") or "").strip().upper()
                    if not s_k:
                        continue
                    ean_val = (
                        m.get("ean")
                        or m.get("ean_base")
                        or m.get("gtin")
                        or m.get("codigo_barras")
                        or m.get("barcode")
                        or m.get("upc")
                        or ""
                    )
                    mapa_maestra_sku[s_k] = {
                        "descripcion": str(m.get("descripcion") or m.get("nombre") or "").strip(),
                        "ean": str(ean_val or "").strip(),
                    }
            except Exception:
                pass

            # 2. Mantener respaldo en memoria de la sesión actual
            for item_mem in registros_locales_mem:
                ov_m = item_mem["ov"]
                agrupado_por_ov[ov_m] = dict(item_mem)

            mapa_clientes_ns = {}
            for item_ns in olas_extraidas_ns:
                k_ov = str(item_ns.get("ov") or "").strip().upper()
                cli_ns = str(item_ns.get("cliente") or "").strip()
                if k_ov and cli_ns:
                    mapa_clientes_ns[k_ov] = cli_ns
                    mapa_clientes_ns[k_ov.replace("-FA", "")] = cli_ns

            # 3. Leer cabeceras desde public.netsuite_ordenes_venta
            mapa_id_a_ov = {}
            for nom_t in ("netsuite_ordenes_venta", "wms_packing_lists_fa"):
                try:
                    res = supabase.table(nom_t).select("*").order("id", desc=True).limit(500).execute()
                    filas_raw = res.data or []
                    if filas_raw and not esquemas_tablas_sb.get(nom_t):
                        esquemas_tablas_sb[nom_t] = list(filas_raw[0].keys())

                    for r in filas_raw:
                        r_copia = dict(r)
                        r_copia["_tabla_origen"] = nom_t
                        info = extraer_campos_registro_ola(r_copia, mapa_clientes_ns)
                        if not info:
                            continue
                        ov_k = info["ov"]
                        if r.get("id") is not None and nom_t == "netsuite_ordenes_venta":
                            mapa_id_a_ov[r.get("id")] = ov_k
                        if ov_k not in agrupado_por_ov:
                            agrupado_por_ov[ov_k] = info
                        else:
                            agrupado_por_ov[ov_k]["id"] = r.get("id") or agrupado_por_ov[ov_k].get("id")
                            agrupado_por_ov[ov_k]["raw"] = info["raw"]
                            agrupado_por_ov[ov_k]["estado"] = info["estado"]
                except Exception:
                    continue

            # 4. Leer líneas desde public.netsuite_detalle_ov usando orden_id
            try:
                res_det = supabase.table("netsuite_detalle_ov").select("*").order("id", desc=False).limit(2000).execute()
                ovs_con_detalle_db = set()
                for d in (res_det.data or []):
                    ord_id = d.get("orden_id")
                    ov_d = mapa_id_a_ov.get(ord_id) or str(d.get("numero_ov") or "").strip().upper()
                    if not ov_d or ov_d not in agrupado_por_ov:
                        continue
                    if ov_d not in ovs_con_detalle_db:
                        agrupado_por_ov[ov_d]["lineas_detalle"] = []
                        ovs_con_detalle_db.add(ov_d)

                    sku_d = str(d.get("sku") or "-").strip().upper()
                    info_m = mapa_maestra_sku.get(sku_d, {})
                    desc_d = str(d.get("descripcion") or info_m.get("descripcion") or "").strip()
                    ean_d = str(d.get("ean") or info_m.get("ean") or "").strip()
                    cant_ped = int(float(d.get("cantidad_pedida") or d.get("cantidad_comprometida") or 0))
                    cant_pick = int(float(d.get("cantidad_pickeada") or 0))
                    lotes_d = str(d.get("lotes_pickeados") or d.get("lote_asignado") or "").strip()
                    if lotes_d.upper() in ("NONE", "NULL"):
                        lotes_d = ""

                    agrupado_por_ov[ov_d]["lineas_detalle"].append({
                        "id_detalle": d.get("id"),
                        "linea_ns": d.get("linea_ns"),
                        "sku": sku_d,
                        "ean": ean_d,
                        "descripcion": desc_d,
                        "cantidad": cant_ped,
                        "cantidad_pedida": cant_ped,
                        "cantidad_pickeada": cant_pick,
                        "lotes": lotes_d,
                        "estado_linea": str(d.get("estado_linea") or "PENDIENTE").upper(),
                        "es_farmacia": agrupado_por_ov[ov_d].get("es_farmacia", False),
                    })

                for ov_c in ovs_con_detalle_db:
                    lins = agrupado_por_ov[ov_c]["lineas_detalle"]
                    agrupado_por_ov[ov_c]["unidades"] = sum(x.get("cantidad_pedida", 0) for x in lins)
                    agrupado_por_ov[ov_c]["unidades_pickeadas"] = sum(x.get("cantidad_pickeada", 0) for x in lins)
            except Exception as ex_d:
                print(f"[WARN] Error leyendo netsuite_detalle_ov: {ex_d}")

            registros_packing_db = list(agrupado_por_ov.values())

            # Incluir también las OVs liberadas en la sesión actual por si la tabla de Supabase tiene otro nombre
            for item_mem in registros_locales_mem:
                ov_m = item_mem["ov"]
                if ov_m not in agrupado_por_ov:
                    agrupado_por_ov[ov_m] = item_mem

            registros_packing_db = list(agrupado_por_ov.values())

        def cambiar_filtro_estado_interno(corte_sel: str):
            nonlocal filtro_corte_activo
            if filtro_corte_activo == corte_sel:
                filtro_corte_activo = "TODOS"
            else:
                filtro_corte_activo = corte_sel
            dd_filtro_corte.value = filtro_corte_activo

        def construir_barra_corte(etiqueta_corte: str, cant_ovs: int, cant_empacadas: int, max_escala: int, fn_click_corte=None):
            altura_max_px = 98
            ratio = min(1.0, cant_ovs / max(1, max_escala))
            alto_barra = max(12, int(ratio * altura_max_px)) if cant_ovs > 0 else 6
            es_completo = cant_ovs > 0 and cant_empacadas >= cant_ovs
            color_b = "#10B981" if es_completo else (ACCENT_BLUE if cant_ovs > 0 else "#334155")

            return ft.Column(
                [
                    ft.Text(f"{cant_ovs} OV", size=10, color=TEXT_WHITE, weight=ft.FontWeight.BOLD),
                    ft.Container(
                        width=42,
                        height=altura_max_px,
                        bgcolor="#141A1C",
                        border_radius=4,
                        alignment=ft.Alignment.BOTTOM_CENTER,
                        ink=True,
                        on_click=fn_click_corte,
                        tooltip=f"Corte {etiqueta_corte}: {cant_ovs} OVs ({cant_empacadas} Empacadas) - Clic para filtrar",
                        content=ft.Container(
                            width=42,
                            height=alto_barra,
                            bgcolor=color_b,
                            border_radius=4,
                        ),
                    ),
                    ft.Text(
                        etiqueta_corte,
                        size=10,
                        color=ACCENT_CYAN if filtro_corte_activo == etiqueta_corte else TEXT_MUTED,
                        weight=ft.FontWeight.BOLD,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=3,
            )

        def mostrar_modal_detalle_ov(ov_num: str, info_ov: dict):
            lineas_det = info_ov.get("lineas_detalle", [])
            filas_d = []
            for ld in lineas_det:
                es_sku_fa = ld.get("es_farmacia", False)
                filas_d.append(
                    ft.Row(
                        [
                            ft.Text(str(ld.get("sku", "-")), size=11, weight=ft.FontWeight.BOLD, color="#FBBF24" if es_sku_fa else ACCENT_CYAN, width=120),
                            ft.Text(str(ld.get("descripcion", "-"))[:38], size=11, color=TEXT_WHITE, expand=True),
                            ft.Text(f"{ld.get('cantidad', 0)} UN", size=11, weight=ft.FontWeight.BOLD, color="#34D399"),
                        ],
                        spacing=8,
                    )
                )
            if not filas_d:
                filas_d.append(ft.Text(f"Cliente: {info_ov.get('cliente', '-')}", size=12, color=TEXT_WHITE))
                filas_d.append(ft.Text(f"Canal: {'FARMACIA (-FA)' if info_ov.get('es_farmacia') else 'ESTÁNDAR'}", size=12, color="#FBBF24" if info_ov.get("es_farmacia") else ACCENT_CYAN))
                filas_d.append(ft.Text(f"Estado Actual: {info_ov.get('estado', '-')}", size=12, color="#34D399"))

            def cerrar_d(ev=None):
                dlg_det.open = False
                try:
                    page.close(dlg_det)
                except Exception:
                    pass
                page.update()

            dlg_det = ft.AlertDialog(
                title=ft.Text(
                    f"Detalle Orden de Venta #{ov_num} (Corte {info_ov.get('corte', '-')})",
                    color=TEXT_WHITE,
                    size=15,
                    weight=ft.FontWeight.BOLD,
                ),
                bgcolor=BG_CARD,
                content=ft.Container(
                    width=540,
                    height=260,
                    padding=10,
                    bgcolor="#181E20",
                    border_radius=6,
                    content=ft.Column(filas_d, spacing=6, scroll=ft.ScrollMode.AUTO),
                ),
                actions=[ft.TextButton("Cerrar", on_click=cerrar_d)],
            )
            try:
                page.open(dlg_det)
            except Exception:
                page.dialog = dlg_det
                dlg_det.open = True
                page.update()

        def cambiar_estado_packing_ov(info_item: dict, nuevo_estado: str):
            ov_cod = info_item.get("ov")
            info_item["estado"] = nuevo_estado
            for m_it in registros_locales_mem:
                if m_it["ov"] == ov_cod:
                    m_it["estado"] = nuevo_estado

            try:
                supabase.table("netsuite_ordenes_venta").update({"estado_ns": nuevo_estado}).eq("numero_ov", ov_cod).execute()
            except Exception:
                pass

            if info_item.get("es_farmacia"):
                for col_est in ("estado_ns", "estado_sanitario", "estado"):
                    try:
                        supabase.table("wms_packing_lists_fa").update({col_est: nuevo_estado}).eq("numero_ov", ov_cod).execute()
                        break
                    except Exception:
                        continue

            notificar(f"OV {ov_cod} actualizada a [{nuevo_estado}].", "#047857")
            recargar_datos_supabase()
            renderizar_monitor_cortes_y_tablas()

        def exportar_ov_farmacia_excel_pdf(info_ov: dict = None):
            import textwrap
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

            objetivos = [info_ov] if info_ov else [r for r in registros_packing_db if r.get("es_farmacia")]
            if not objetivos:
                notificar("No hay OVs de Farmacia (-FA) cargadas para exportar.", "#D97706")
                return

            # 1. Cargar maestra_sku para obtener EAN / GTIN Base y Descripción real
            mapa_sku_info = {}
            try:
                res_m = supabase.table("maestra_sku").select("*").limit(4000).execute()
                for m in (res_m.data or []):
                    s_k = str(m.get("sku") or "").strip().upper()
                    if not s_k:
                        continue
                    ean_v = (
                        m.get("ean")
                        or m.get("ean_base")
                        or m.get("gtin")
                        or m.get("codigo_barras")
                        or m.get("barcode")
                        or m.get("upc")
                        or ""
                    )
                    mapa_sku_info[s_k] = {
                        "descripcion": str(m.get("descripcion") or m.get("nombre") or "").strip(),
                        "ean": str(ean_v or "").strip(),
                    }
            except Exception:
                pass

            def esc_pdf(txt: str) -> str:
                s = str(txt or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                return s.encode("cp1252", "replace").decode("latin-1")

            try:
                os.makedirs("reportes_farmacia", exist_ok=True)
                ahora_dt = datetime.now()
                ts_arch = ahora_dt.strftime("%Y%m%d_%H%M%S")
                fecha_emision_str = ahora_dt.strftime("%d-%m-%Y %H:%M")

                archivos_generados = []

                for ov_reg in objetivos:
                    ov_raw = str(ov_reg.get("ov") or "OV").strip().upper()
                    ov_limpia = ov_raw.removesuffix("-FA").strip()
                    cli_nom = str(ov_reg.get("cliente") or "CLIENTE FARMACIA").strip()
                    id_ov_db = ov_reg.get("id")

                    # Buscar id de la orden en netsuite_ordenes_venta si no estaba en memoria
                    if id_ov_db is None:
                        try:
                            r_cab = supabase.table("netsuite_ordenes_venta").select("id, cliente_nombre").or_(f"numero_ov.eq.{ov_raw},numero_ov.eq.{ov_limpia}").limit(1).execute()
                            if r_cab.data:
                                id_ov_db = r_cab.data[0].get("id")
                                if r_cab.data[0].get("cliente_nombre"):
                                    cli_nom = str(r_cab.data[0]["cliente_nombre"]).strip()
                        except Exception:
                            pass

                    # Consultar líneas reales y lo pickeado en netsuite_detalle_ov
                    lineas_exportar = []
                    if id_ov_db is not None:
                        try:
                            r_det = supabase.table("netsuite_detalle_ov").select("*").eq("orden_id", id_ov_db).order("linea_ns", desc=False).execute()
                            for d in (r_det.data or []):
                                sku_c = str(d.get("sku") or "").strip().upper()
                                info_m = mapa_sku_info.get(sku_c, {})
                                ean_c = str(info_m.get("ean") or d.get("ean") or sku_c).strip()
                                desc_c = str(info_m.get("descripcion") or d.get("descripcion") or "").strip()
                                sol_c = int(float(d.get("cantidad_pedida") or d.get("cantidad_comprometida") or 0))
                                pick_c = int(float(d.get("cantidad_pickeada") or 0))
                                lotes_c = str(d.get("lotes_pickeados") or d.get("lote_asignado") or "").strip()
                                if lotes_c.upper() in ("NONE", "NULL"):
                                    lotes_c = ""
                                lineas_exportar.append({
                                    "sku": sku_c,
                                    "ean": ean_c,
                                    "descripcion": desc_c,
                                    "solicitado": sol_c,
                                    "pickeado": pick_c,
                                    "lotes": lotes_c,
                                })
                        except Exception:
                            pass

                    # Respaldo desde memoria enriquecido con maestra_sku
                    if not lineas_exportar:
                        for ld in (ov_reg.get("lineas_detalle") or []):
                            sku_c = str(ld.get("sku") or "").strip().upper()
                            info_m = mapa_sku_info.get(sku_c, {})
                            ean_c = str(ld.get("ean") or info_m.get("ean") or sku_c).strip()
                            desc_c = str(ld.get("descripcion") or info_m.get("descripcion") or "").strip()
                            sol_c = int(float(ld.get("cantidad_pedida") or ld.get("cantidad") or 0))
                            pick_c = int(float(ld.get("cantidad_pickeada") or 0))
                            lotes_c = str(ld.get("lotes") or ld.get("lotes_pickeados") or ld.get("lote_asignado") or "").strip()
                            lineas_exportar.append({
                                "sku": sku_c,
                                "ean": ean_c,
                                "descripcion": desc_c,
                                "solicitado": sol_c,
                                "pickeado": pick_c,
                                "lotes": lotes_c,
                            })

                    ruta_excel = os.path.join("reportes_farmacia", f"PackingList_FA_{ov_limpia}_{ts_arch}.xlsx")
                    ruta_pdf = os.path.join("reportes_farmacia", f"PackingList_FA_{ov_limpia}_{ts_arch}.pdf")

                    # =========================================================================
                    # A) GENERAR EXCEL (.XLSX) CON FORMATO CORPORATIVO LUDIPEK WMS
                    # =========================================================================
                    wb = openpyxl.Workbook()
                    ws = wb.active
                    ws.title = "Packing_FA"

                    ws["A1"] = "LUDIPEK WMS"
                    ws["A1"].font = Font(name="Calibri", size=16, bold=True, color="1E3A8A")

                    ws["G2"] = "PACKING LIST - FARMACIA (FA)"
                    ws["G2"].font = Font(name="Calibri", size=14, bold=True, color="000000")
                    ws["G2"].alignment = Alignment(horizontal="right")

                    ws["G3"] = f"Fecha de Emisión: {fecha_emision_str}"
                    ws["G3"].font = Font(name="Calibri", size=11, bold=False, color="64748B")
                    ws["G3"].alignment = Alignment(horizontal="right")

                    encabezados = [
                        "ORDEN DE VENTA",
                        "CLIENTE",
                        "SKU",
                        "EAN / GTIN Base",
                        "Descripción",
                        "Solicitado",
                        "Pickeado",
                        "Lotes Trazabilidad",
                    ]
                    fill_hdr = PatternFill(fill_type="solid", start_color="1E3A8A", end_color="1E3A8A")
                    font_hdr = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                    borde_fino = Side(style="thin", color="CBD5E1")
                    border_celda = Border(left=borde_fino, right=borde_fino, top=borde_fino, bottom=borde_fino)

                    for col_idx, texto_h in enumerate(encabezados, start=1):
                        c = ws.cell(row=5, column=col_idx, value=texto_h)
                        c.fill = fill_hdr
                        c.font = font_hdr
                        c.alignment = Alignment(horizontal="center", vertical="center")
                        c.border = border_celda

                    for r_idx, lin in enumerate(lineas_exportar, start=6):
                        valores_fila = [
                            ov_limpia,
                            cli_nom,
                            lin["sku"],
                            lin["ean"],
                            lin["descripcion"],
                            int(lin["solicitado"]),
                            int(lin["pickeado"]),
                            lin["lotes"],
                        ]
                        for c_idx, val in enumerate(valores_fila, start=1):
                            celda = ws.cell(row=r_idx, column=c_idx, value=val)
                            celda.font = Font(name="Calibri", size=11, bold=False)
                            celda.border = border_celda
                            if c_idx in (1, 3, 4, 6, 7):
                                celda.alignment = Alignment(horizontal="center", vertical="center")
                            else:
                                celda.alignment = Alignment(horizontal="left", vertical="center", wrap_text=(c_idx == 8))

                    anchos_cols = {"A": 15.0, "B": 35.0, "C": 15.0, "D": 22.0, "E": 45.0, "F": 11.0, "G": 13.0, "H": 70.0}
                    for col_l, w_val in anchos_cols.items():
                        ws.column_dimensions[col_l].width = w_val

                    wb.save(ruta_excel)

                    # =========================================================================
                    # B) GENERAR PDF (.PDF) HORIZONTAL SIN DESBORDES DE BORDES
                    # =========================================================================
                    cmds = [
                        "2 J",
                        "0.57 w",
                        "BT /F1 22.00 Tf ET",
                        "q BT 42.52 531.99 Td 0.1176 0.2275 0.5412 rg (LUDIPEK) Tj ET Q",
                        "BT /F1 18.00 Tf ET",
                        "q BT 519.40 536.02 Td 0 g (PACKING LIST - FARMACIA \\(FA\\)) Tj ET Q",
                        "BT /F2 10.00 Tf ET",
                        f"q BT 625.00 517.16 Td 0.3922 0.4549 0.5451 rg (Fecha de Emisión: {esc_pdf(fecha_emision_str)}) Tj ET Q",
                        # Recuadro gris de cabecera (x=39.69 a 802.21)
                        "0.9451 0.9608 0.9765 rg",
                        "0.7961 0.8353 0.8824 RG",
                        "39.69 481.89 762.52 -45.35 re B",
                        # Clipping estricto dentro del recuadro gris para evitar que el cliente se salga del borde
                        "q 39.69 436.54 758.00 45.35 re W n",
                        "BT /F1 12.00 Tf ET",
                        f"BT 53.86 455.32 Td 0 g (ORDEN DE VENTA: {esc_pdf(ov_limpia)}) Tj ET",
                        f"BT 310.00 455.32 Td 0 g (CLIENTE: {esc_pdf(cli_nom[:52])}) Tj ET",
                        "Q",
                    ]

                    cols_def = [
                        ("SKU", 39.69, 95.0, "L"),
                        ("EAN / GTIN Base", 134.69, 105.0, "L"),
                        ("Descripción", 239.69, 245.0, "L"),
                        ("Sol.", 484.69, 42.0, "C"),
                        ("Pick.", 526.69, 42.0, "C"),
                        ("Lotes Trazabilidad (y Venc.)", 568.69, 233.52, "L"),
                    ]

                    y_top = 411.03
                    h_hdr = 22.68
                    cmds.append("0.1176 0.2275 0.5412 rg")
                    cmds.append("0.0588 0.0902 0.1647 RG")
                    cmds.append("BT /F1 10.00 Tf ET")
                    for titulo, cx, cw, _ in cols_def:
                        tx = cx + max(4.0, (cw - len(titulo) * 5.2) / 2.0)
                        ty = y_top - 14.34
                        cmds.append(
                            f"q {cx:.2f} {y_top:.2f} {cw:.2f} -{h_hdr:.2f} re B BT {tx:.2f} {ty:.2f} Td 1 1 1 rg ({esc_pdf(titulo)}) Tj ET Q"
                        )

                    y_curr = y_top - h_hdr
                    for lin in lineas_exportar[:14]:
                        lotes_txt = str(lin.get("lotes") or "").strip()
                        desc_txt = str(lin.get("descripcion") or "").strip()
                        ean_txt = str(lin.get("ean") or "").strip()
                        sku_txt = str(lin.get("sku") or "").strip()

                        # Envolver textos largos en hasta 2 líneas para que entren dentro del ancho de cada celda
                        lotes_lines = textwrap.wrap(lotes_txt, width=46)[:2] if lotes_txt else [""]
                        desc_lines = textwrap.wrap(desc_txt, width=46)[:2] if desc_txt else [""]
                        ean_lines = textwrap.wrap(ean_txt, width=19)[:2] if ean_txt else [""]

                        max_lines = max(len(lotes_lines), len(desc_lines), len(ean_lines), 1)
                        row_h = 22.68 if max_lines == 1 else 28.0

                        celdas_vals = [
                            ([sku_txt[:18]], cols_def[0]),
                            (ean_lines, cols_def[1]),
                            (desc_lines, cols_def[2]),
                            ([str(int(lin.get("solicitado", 0)))], cols_def[3]),
                            ([str(int(lin.get("pickeado", 0)))], cols_def[4]),
                            (lotes_lines, cols_def[5]),
                        ]

                        for lista_txt, (_, cx, cw, align_c) in celdas_vals:
                            cmds.append(f"q 0.5588 0.6353 0.7224 RG {cx:.2f} {y_curr:.2f} {cw:.2f} -{row_h:.2f} re S Q")
                            # Máscara de recorte por celda (impide que cualquier letra cruce la línea divisoria)
                            cmds.append(f"q {cx+1.5:.2f} {y_curr-row_h+1.0:.2f} {cw-3.0:.2f} {row_h-2.0:.2f} re W n")
                            font_sz = 8.5 if len(lista_txt) > 1 else 9.0
                            cmds.append(f"BT /F2 {font_sz:.2f} Tf ET")
                            if len(lista_txt) == 1:
                                t_val = lista_txt[0]
                                tx = (cx + max(2.0, (cw - len(t_val) * 4.8) / 2.0)) if align_c == "C" else (cx + 4.0)
                                ty = y_curr - (row_h / 2.0) - 3.0
                                cmds.append(f"BT {tx:.2f} {ty:.2f} Td 0 g ({esc_pdf(t_val)}) Tj ET")
                            else:
                                for idx_ln, t_val in enumerate(lista_txt):
                                    tx = cx + 4.0
                                    ty = y_curr - 10.5 - (idx_ln * 10.5)
                                    cmds.append(f"BT {tx:.2f} {ty:.2f} Td 0 g ({esc_pdf(t_val)}) Tj ET")
                            cmds.append("Q")

                        y_curr -= row_h

                    # Firmas al pie (PREPARADO POR / REVISADO QA)
                    y_sig = min(181.42, y_curr - 40.0)
                    if y_sig < 48.0:
                        y_sig = 48.0
                    cmds.extend([
                        "0 G",
                        f"155.91 {y_sig:.2f} m 325.98 {y_sig:.2f} l S",
                        f"524.41 {y_sig:.2f} m 694.49 {y_sig:.2f} l S",
                        "BT /F1 10.00 Tf ET",
                        f"q BT 196.77 {y_sig - 18.59:.2f} Td 0 g (PREPARADO POR) Tj ET Q",
                        f"q BT 574.44 {y_sig - 18.59:.2f} Td 0 g (REVISADO QA) Tj ET Q",
                    ])

                    stream_bytes = "\n".join(cmds).encode("latin-1")
                    objetos_pdf = [
                        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
                        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
                        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 841.89 595.28] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>\nendobj\n",
                        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>\nendobj\n",
                        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj\n",
                        f"6 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1") + stream_bytes + b"\nendstream\nendobj\n",
                    ]
                    pdf_bytes = bytearray(b"%PDF-1.4\n")
                    offsets = []
                    for obj in objetos_pdf:
                        offsets.append(len(pdf_bytes))
                        pdf_bytes.extend(obj)
                    xref_pos = len(pdf_bytes)
                    pdf_bytes.extend(f"xref\n0 {len(objetos_pdf)+1}\n0000000000 65535 f \n".encode("latin-1"))
                    for off in offsets:
                        pdf_bytes.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
                    pdf_bytes.extend(
                        f"trailer\n<< /Size {len(objetos_pdf)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode("latin-1")
                    )
                    with open(ruta_pdf, "wb") as f_pdf:
                        f_pdf.write(pdf_bytes)

                    descargar_o_abrir_archivo(self.page, ruta_pdf)
                    descargar_o_abrir_archivo(self.page, ruta_excel)
                    archivos_generados.append(f"PackingList_FA_{ov_limpia}")

                notificar(
                    f"Excel y PDF generados y descargados ({', '.join(archivos_generados[:2])}).",
                    "#047857",
                )
            except Exception as ex:
                notificar(f"Error al generar Packing List FA: {ex}", "#B91C1C")

        def renderizar_monitor_cortes_y_tablas():
            txt_t, col_t = obtener_tip_corte_actual()
            lbl_tip_corte.value = txt_t
            lbl_tip_corte.color = col_t

            mapa_ovs_unicas = {}
            for item_db in registros_packing_db:
                mapa_ovs_unicas[item_db["ov"]] = item_db
            for item_ns in olas_extraidas_ns:
                if item_ns["ov"] not in mapa_ovs_unicas:
                    mapa_ovs_unicas[item_ns["ov"]] = item_ns

            todas_ovs = list(mapa_ovs_unicas.values())

            cortes_orden = ["09:00", "10:00", "12:00", "13:00", ">13:00"]
            agrupado_cortes = {c: [] for c in cortes_orden}
            for item in todas_ovs:
                c_key = item.get("corte", "09:00")
                if c_key not in agrupado_cortes:
                    c_key = ">13:00"
                agrupado_cortes[c_key].append(item)

            # Actualizar Relojes Digitales de Cortes (09, 10, 12, 13 hrs)
            lbl_corte_09.value = f"{len(agrupado_cortes['09:00']):02d}"
            lbl_corte_10.value = f"{len(agrupado_cortes['10:00']):02d}"
            lbl_corte_12.value = f"{len(agrupado_cortes['12:00']):02d}"
            lbl_corte_13.value = f"{len(agrupado_cortes['13:00']):02d}"

            # Para los contadores inferiores, si ya hay OVs en Packing usamos registros_packing_db; si aún están en previsualización, mostramos el conteo de todas_ovs
            fuente_kpis = registros_packing_db if registros_packing_db else todas_ovs
            ovs_kpi_filtradas = [
                r for r in fuente_kpis
                if filtro_corte_activo == "TODOS" or r.get("corte") == filtro_corte_activo
            ]

            normales_kpi = [r for r in ovs_kpi_filtradas if not r.get("es_farmacia")]
            farmacias_kpi = [r for r in ovs_kpi_filtradas if r.get("es_farmacia")]

            ovs_pack_filtradas = [
                r for r in registros_packing_db
                if filtro_corte_activo == "TODOS" or r.get("corte") == filtro_corte_activo
            ]
            normales_pack = [r for r in ovs_pack_filtradas if not r.get("es_farmacia")]
            farmacias_pack = [r for r in ovs_pack_filtradas if r.get("es_farmacia")]

            empacadas_cnt = sum(
                1 for r in ovs_pack_filtradas if r.get("estado") in ("EMPACADO", "COMPLETADO", "DESPACHADO", "CERRADO")
            )

            lbl_kpi_total_ovs.value = str(len(ovs_kpi_filtradas))
            lbl_kpi_ov_normal.value = str(len(normales_kpi))
            lbl_kpi_ov_farma.value = str(len(farmacias_kpi))
            pct_pack = int(round((empacadas_cnt / max(1, len(ovs_pack_filtradas))) * 100)) if ovs_pack_filtradas else 0
            lbl_kpi_avance_pack.value = f"{pct_pack}%"

            # Construir Gráfico de Barras y Desglose de Números de OV por Corte
            fila_barras_cortes.controls.clear()
            col_detalle_ovs_por_corte.controls.clear()
            max_corte_cnt = max([len(v) for v in agrupado_cortes.values()] + [1])

            for c_label in cortes_orden:
                lista_c = agrupado_cortes[c_label]
                emp_c = sum(1 for x in lista_c if x.get("estado") in ("EMPACADO", "COMPLETADO", "DESPACHADO"))
                fila_barras_cortes.controls.append(
                    construir_barra_corte(
                        c_label,
                        len(lista_c),
                        emp_c,
                        max_corte_cnt,
                        lambda e, c=c_label: (cambiar_filtro_estado_interno(c), renderizar_monitor_cortes_y_tablas()),
                    )
                )

                if lista_c:
                    chips_ov = []
                    for x_ov in lista_c[:12]:
                        es_emp = x_ov.get("estado") in ("EMPACADO", "COMPLETADO")
                        es_fa = x_ov.get("es_farmacia")
                        chips_ov.append(
                            ft.Container(
                                padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                                bgcolor="#065F46" if es_emp else ("#78350F" if es_fa else "#1E3A8A"),
                                border_radius=4,
                                border=ft.Border.all(1, "#34D399" if es_emp else ("#FBBF24" if es_fa else "#38BDF8")),
                                tooltip=f"OV {x_ov['ov']} | {x_ov['cliente']} | {'FARMACIA (-FA)' if es_fa else 'ESTÁNDAR'} | {x_ov['estado']}",
                                on_click=lambda ev, ov_s=x_ov["ov"], inf=x_ov: mostrar_modal_detalle_ov(ov_s, inf),
                                content=ft.Text(
                                    f"OV {x_ov['ov']}",
                                    size=10,
                                    weight=ft.FontWeight.BOLD,
                                    color=TEXT_WHITE,
                                ),
                            )
                        )
                    if len(lista_c) > 12:
                        chips_ov.append(ft.Text(f"+{len(lista_c) - 12} más", size=10, color=TEXT_MUTED))
                else:
                    chips_ov = [ft.Text("Sin OVs en este corte", size=10, color="#64748B")]

                col_detalle_ovs_por_corte.controls.append(
                    ft.Container(
                        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                        bgcolor="#141A1C",
                        border_radius=6,
                        border=ft.Border.all(1, ACCENT_CYAN if filtro_corte_activo == c_label else "#2B3537"),
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(f"⏱️ CORTE {c_label} HRS", size=11, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
                                        ft.Text(
                                            f"{len(lista_c)} OVs ({emp_c} Empacadas)",
                                            size=10,
                                            weight=ft.FontWeight.W_600,
                                            color="#34D399" if emp_c == len(lista_c) and lista_c else TEXT_MUTED,
                                        ),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                                ft.Row(chips_ov, wrap=True, spacing=5, run_spacing=4),
                            ],
                            spacing=4,
                        ),
                    )
                )

            # Llenar Tabla Línea 1: OV Estándar
            tabla_packing_normal.rows.clear()
            for r_norm in normales_pack:
                est_n = r_norm["estado"]
                badge_n = (
                    crear_badge_estado(est_n, "#065F46", "#D1FAE5")
                    if est_n in ("EMPACADO", "COMPLETADO", "LIBERADO")
                    else crear_badge_estado(est_n, "#92400E", "#FEF3C7")
                )
                tabla_packing_normal.rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(r_norm["ov"], weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(f"{r_norm['corte']} hrs", size=11, weight=ft.FontWeight.BOLD, color="#A78BFA")),
                            ft.DataCell(ft.Text(r_norm["cliente"][:26], size=11, color=TEXT_WHITE)),
                            ft.DataCell(badge_n),
                            ft.DataCell(
                                boton_primario(
                                    "EMPACAR",
                                    ft.Icons.INVENTORY_2_OUTLINED,
                                    lambda ev, it=r_norm: cambiar_estado_packing_ov(it, "EMPACADO"),
                                    "#047857" if est_n != "EMPACADO" else "#334155",
                                    height_val=26,
                                )
                            ),
                        ]
                    )
                )

            # Llenar Tabla Línea 2: OV Farmacia (-FA)
            tabla_packing_farmacia.rows.clear()
            for r_fa in farmacias_pack:
                est_f = r_fa["estado"]
                badge_f = (
                    crear_badge_estado(est_f, "#065F46", "#D1FAE5")
                    if est_f in ("EMPACADO", "COMPLETADO", "LIBERADO")
                    else crear_badge_estado(est_f, "#92400E", "#FEF3C7")
                )
                tabla_packing_farmacia.rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(r_fa["ov"], weight=ft.FontWeight.BOLD, size=11, color="#FBBF24")),
                            ft.DataCell(ft.Text(f"{r_fa['corte']} hrs", size=11, weight=ft.FontWeight.BOLD, color="#A78BFA")),
                            ft.DataCell(ft.Text(r_fa["cliente"][:26], size=11, color=TEXT_WHITE)),
                            ft.DataCell(badge_f),
                            ft.DataCell(
                                ft.Row(
                                    [
                                        boton_primario(
                                            "VALIDAR -FA",
                                            ft.Icons.VERIFIED_USER_OUTLINED,
                                            lambda ev, it=r_fa: (cambiar_estado_packing_ov(it, "EMPACADO"), exportar_ov_farmacia_excel_pdf(it)),
                                            "#0F766E" if est_f != "EMPACADO" else "#334155",
                                            height_val=26,
                                        ),
                                        boton_primario(
                                            "XLS / PDF",
                                            ft.Icons.DOWNLOAD_ROUNDED,
                                            lambda ev, it=r_fa: exportar_ov_farmacia_excel_pdf(it),
                                            "#B45309",
                                            height_val=26,
                                        ),
                                    ],
                                    spacing=6,
                                    tight=True,
                                )
                            ),
                        ]
                    )
                )

            page.update()

        def aplicar_filtro_corte_rapido(corte_sel: str):
            cambiar_filtro_estado_interno(corte_sel)
            renderizar_monitor_cortes_y_tablas()

        def cambiar_filtro_corte_dropdown(e=None):
            nonlocal filtro_corte_activo
            filtro_corte_activo = dd_filtro_corte.value or "TODOS"
            renderizar_monitor_cortes_y_tablas()

        dd_filtro_corte.on_select = cambiar_filtro_corte_dropdown

        def cargar_monitor_packing_dual(e=None):
            recargar_datos_supabase()
            renderizar_monitor_cortes_y_tablas()

        # --- 8. EXTRACCIÓN DE OLAS DESDE NETSUITE, SEPARACIÓN (-FA) Y LIBERACIÓN A RF ---
        def alternar_canal_farmacia_manual(item_ola: dict):
            es_fa_nuevo = not item_ola.get("es_farmacia", False)
            item_ola["es_farmacia"] = es_fa_nuevo
            ov_base = str(item_ola["ov"]).removesuffix("-FA").strip()
            item_ola["ov"] = f"{ov_base}-FA" if es_fa_nuevo else ov_base
            renderizar_tabla_previsualizacion()

        def cambiar_check_individual(e, item_ola: dict):
            item_ola["seleccionada"] = bool(e.control.value)

        def renderizar_tabla_previsualizacion():
            tabla_previsualizacion_ns.rows.clear()
            checks_liberacion.clear()

            for item in olas_extraidas_ns:
                ov_cod = item["ov"]
                est_sel = item.get("seleccionada", True)
                chk = ft.Checkbox(
                    value=est_sel,
                    active_color=ACCENT_CYAN,
                    on_change=lambda e, it=item: cambiar_check_individual(e, it),
                )
                checks_liberacion[ov_cod] = chk
                es_fa = item.get("es_farmacia", False)
                badge_canal = ft.Container(
                    ink=True,
                    tooltip="Clic para cambiar entre ESTÁNDAR y FARMACIA (-FA)",
                    on_click=lambda e, it=item: alternar_canal_farmacia_manual(it),
                    content=(
                        crear_badge_estado("FARMACIA (-FA)", "#92400E", "#FEF3C7")
                        if es_fa
                        else crear_badge_estado("ESTÁNDAR", "#1E3A8A", "#DBEAFE")
                    ),
                )

                tabla_previsualizacion_ns.rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(chk),
                            ft.DataCell(ft.Text(ov_cod, weight=ft.FontWeight.BOLD, size=11, color="#FBBF24" if es_fa else ACCENT_CYAN)),
                            ft.DataCell(ft.Text(f"⏱️ {item.get('corte', '09:00')} hrs", weight=ft.FontWeight.BOLD, size=11, color="#A78BFA")),
                            ft.DataCell(badge_canal),
                            ft.DataCell(ft.Text(item["cliente"][:30], size=11, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(str(item.get("lineas_cnt", 1)), size=11, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(f"{item.get('unidades', 0)} UN", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                            ft.DataCell(
                                boton_primario(
                                    "VER SKUs",
                                    ft.Icons.VISIBILITY_OUTLINED,
                                    lambda ev, cod=ov_cod, inf=item: mostrar_modal_detalle_ov(cod, inf),
                                    ACCENT_TEAL,
                                    height_val=26,
                                )
                            ),
                        ]
                    )
                )
            renderizar_monitor_cortes_y_tablas()

        def marcar_todas_olas(e=None):
            for item in olas_extraidas_ns:
                item["seleccionada"] = True
            renderizar_tabla_previsualizacion()
            notificar(f"Todas las {len(olas_extraidas_ns)} olas han sido marcadas.", ACCENT_TEAL)

        def marcar_solo_farmacia_olas(e=None):
            cont_fa = 0
            for item in olas_extraidas_ns:
                es_fa = bool(item.get("es_farmacia", False))
                item["seleccionada"] = es_fa
                if es_fa:
                    cont_fa += 1
            renderizar_tabla_previsualizacion()
            notificar(f"Se marcaron únicamente las {cont_fa} olas de Farmacia (-FA).", "#D97706")

        def desmarcar_todas_olas(e=None):
            for item in olas_extraidas_ns:
                item["seleccionada"] = False
            renderizar_tabla_previsualizacion()
            notificar("Todas las olas han sido desmarcadas.", "#475569")

        def obtener_skus_farmacia_supabase() -> set:
            skus_fa = set()
            try:
                # 1. Traer de maestra_sku todos los SKUs de marca BOEHRINGER o ubicación PICK-FARM
                res_b = (
                    supabase.table("maestra_sku")
                    .select("sku, marca, ubicacion_picking_fija")
                    .or_("marca.ilike.%BOEHRINGER%,ubicacion_picking_fija.ilike.%PICK-FARM%,ubicacion_picking_fija.ilike.%FARM%")
                    .limit(5000)
                    .execute()
                )
                for row in (res_b.data or []):
                    sku_c = str(row.get("sku") or "").strip().upper()
                    if sku_c:
                        skus_fa.add(sku_c)
            except Exception:
                pass

            # 2. Respaldo en caso de lectura completa de maestra_sku
            if not skus_fa:
                try:
                    res_m = supabase.table("maestra_sku").select("sku, marca, ubicacion_picking_fija").limit(5000).execute()
                    for row in (res_m.data or []):
                        sku_c = str(row.get("sku") or "").strip().upper()
                        marca_c = str(row.get("marca") or "").strip().upper()
                        ubic_fija = str(row.get("ubicacion_picking_fija") or "").strip().upper()
                        if sku_c and ("BOEHRINGER" in marca_c or "PICK-FARM" in ubic_fija or "FARMACIA" in ubic_fija):
                            skus_fa.add(sku_c)
                except Exception:
                    pass

            return skus_fa

        def extraer_ordenes_netsuite(e=None):
            nonlocal olas_extraidas_ns
            f_desde = (txt_fecha_desde.value or "").strip()
            f_hasta = (txt_fecha_hasta.value or "").strip()

            if not NETSUITE_CONECTADO:
                notificar("Módulo conexion_erp no conectado. Mostrando OVs activas en Supabase.", "#D97706")
                cargar_monitor_packing_dual()
                return

            txt_estado_erp.value = f"Consultando OVs en NetSuite ({f_desde} a {f_hasta}) y separando líneas Normal vs Farmacia (-FA)..."
            txt_estado_erp.color = ACCENT_CYAN
            page.update()

            try:
                skus_fa_catalogo = obtener_skus_farmacia_supabase()

                q_ov = f"""
                    SELECT
                        t.id AS ov_internal_id,
                        t.tranid AS numero_ov,
                        t.memo AS memo_ov,
                        TO_CHAR(t.createddate, 'YYYY-MM-DD HH24:MI:SS') AS fecha_hora,
                        BUILTIN.DF(t.entity) AS cliente,
                        BUILTIN.DF(tl.location) AS bodega_ns,
                        i.itemid AS sku,
                        BUILTIN.DF(i.id) AS descripcion,
                        ABS(tl.quantity) AS cantidad
                    FROM transaction t
                    INNER JOIN transactionline tl ON t.id = tl.transaction
                    INNER JOIN item i ON tl.item = i.id
                    WHERE t.type = 'SalesOrd'
                    AND tl.mainline = 'F'
                    AND t.trandate >= TO_DATE('{f_desde}', 'YYYY-MM-DD')
                    AND t.trandate <= TO_DATE('{f_hasta}', 'YYYY-MM-DD')
                    ORDER BY t.id DESC
                """
                try:
                    df_ov = consultar_netsuite(q_ov)
                except Exception:
                    q_fallback = f"""
                        SELECT
                            t.id AS ov_internal_id,
                            t.tranid AS numero_ov,
                            t.trandate AS fecha_hora,
                            BUILTIN.DF(t.entity) AS cliente,
                            i.itemid AS sku,
                            BUILTIN.DF(i.id) AS descripcion,
                            ABS(tl.quantity) AS cantidad
                        FROM transaction t
                        INNER JOIN transactionline tl ON t.id = tl.transaction
                        INNER JOIN item i ON tl.item = i.id
                        WHERE t.type = 'SalesOrd'
                        AND tl.mainline = 'F'
                        ORDER BY t.id DESC
                    """
                    df_ov = consultar_netsuite(q_fallback)

                if df_ov is None or df_ov.empty:
                    notificar("No se encontraron Órdenes de Venta en NetSuite para el rango indicado.", "#D97706")
                    txt_estado_erp.value = "Sin resultados en NetSuite para el rango seleccionado."
                    page.update()
                    return

                # Separamos automáticamente cada OV en su parte NORMAL y su parte FARMACIA (-FA) si contiene SKUs/bodega de Farmacia
                agrupado_olas = {}
                corte_forzado_ui = None if dd_corte_asignar.value == "AUTO" else dd_corte_asignar.value

                for _, fila in df_ov.iterrows():
                    cant_item = int(float(fila.get("cantidad") or 0))
                    if cant_item <= 0:
                        continue
                    ov_raw = str(fila.get("numero_ov") or "").strip()
                    if not ov_raw:
                        continue
                    sku_str = str(fila.get("sku") or "").strip().upper()
                    # Ignorar líneas de despacho/flete o impuestos sin SKU físico si vinieran vacías
                    if not sku_str or sku_str in ("NONE", "NULL"):
                        continue

                    desc_str = str(fila.get("descripcion") or "").strip()
                    cli_str = str(fila.get("cliente") or "CLIENTE").strip()
                    fh_str = str(fila.get("fecha_hora") or "")
                    bodega_ns = str(fila.get("bodega_ns") or "")
                    memo_ov = str(fila.get("memo_ov") or "")

                    # SOLO es Farmacia (-FA) si el SKU está en maestra_sku como BOEHRINGER / PICK-FARM
                    es_linea_fa = (
                        sku_str in skus_fa_catalogo
                        or detectar_es_farmacia_texto(ov_raw, bodega_ns)
                    )

                    ov_base = ov_raw.removesuffix("-FA").strip()
                    ov_clave = f"{ov_base}-FA" if es_linea_fa else ov_base
                    ubic_linea = "PICK-FARM" if es_linea_fa else "ZONA-PICKING"

                    if ov_clave not in agrupado_olas:
                        agrupado_olas[ov_clave] = {
                            "ov": ov_clave,
                            "ov_original": ov_raw,
                            "cliente": cli_str,
                            "fecha_hora": fh_str,
                            "corte": clasificar_corte_horario(fh_str, corte_forzado_ui),
                            "es_farmacia": es_linea_fa,
                            "unidades": 0,
                            "lineas_cnt": 0,
                            "estado": "PREVISUALIZADA",
                            "seleccionada": True,
                            "lineas_detalle": [],
                        }
                    agrupado_olas[ov_clave]["unidades"] += cant_item
                    agrupado_olas[ov_clave]["lineas_cnt"] += 1
                    agrupado_olas[ov_clave]["lineas_detalle"].append(
                        {
                            "sku": sku_str,
                            "descripcion": desc_str,
                            "cantidad": cant_item,
                            "ubicacion": ubic_linea,
                            "es_farmacia": es_linea_fa,
                        }
                    )

                olas_extraidas_ns = list(agrupado_olas.values())
                cant_fa = sum(1 for x in olas_extraidas_ns if x.get("es_farmacia"))
                cant_norm = len(olas_extraidas_ns) - cant_fa
                txt_estado_erp.value = (
                    f"Extracción exitosa: {len(olas_extraidas_ns)} Olas ({cant_norm} Estándar | {cant_fa} Farmacia -FA)."
                )
                txt_estado_erp.color = "#34D399"
                notificar(
                    f"{len(olas_extraidas_ns)} Olas extraídas ({cant_norm} Normal y {cant_fa} Farmacia -FA).",
                    "#047857",
                )
                renderizar_tabla_previsualizacion()
            except Exception as ex:
                txt_estado_erp.value = f"Error consultando NetSuite: {ex}"
                txt_estado_erp.color = "#F87171"
                notificar(f"Error extrayendo OVs: {ex}", "#B91C1C")
                page.update()

        def construir_payload_adaptativo(columnas_tabla: list, item: dict, linea_sku: dict = None) -> dict:
            ov_str = item["ov"]
            if item.get("es_farmacia") and not ov_str.upper().endswith("-FA"):
                ov_str = f"{ov_str}-FA"
            cli_str = item["cliente"]
            corte_str = item.get("corte", "09:00")
            es_fa = bool(item.get("es_farmacia"))
            tipo_str = "FARMACIA (-FA)" if es_fa else "ESTANDAR"
            sku_val = (linea_sku or {}).get("sku") or (item.get("lineas_detalle") or [{}])[0].get("sku", "VARIOS")
            desc_val = (linea_sku or {}).get("descripcion") or (item.get("lineas_detalle") or [{}])[0].get("descripcion", "")
            cant_val = int((linea_sku or {}).get("cantidad") or item.get("unidades", 1))

            if not columnas_tabla:
                return {"numero_ov": ov_str, "cliente": cli_str, "estado": "PENDIENTE_PICKING"}

            payload = {}
            cols_set = {c.lower(): c for c in columnas_tabla}

            # Mapear Orden de Venta / Ola
            for cand in ("numero_ov", "orden_venta", "ov", "codigo_ola", "numero_ola", "tranid", "documento"):
                if cand in cols_set:
                    payload[cols_set[cand]] = ov_str
                    break

            # Mapear Cliente
            for cand in ("cliente", "nombre_cliente", "razon_social", "entity"):
                if cand in cols_set:
                    payload[cols_set[cand]] = cli_str
                    break

            # Mapear Estado
            for cand in ("estado", "estado_actual", "estado_packing", "estado_picking", "estado_sanitario"):
                if cand in cols_set:
                    payload[cols_set[cand]] = "PENDIENTE_PICKING"

            # Mapear Tipo / Canal / Farmacia
            for cand in ("tipo_ola", "canal", "zona", "linea_packing", "tipo_ov", "categoria"):
                if cand in cols_set:
                    payload[cols_set[cand]] = tipo_str
            if "es_farmacia" in cols_set:
                payload[cols_set["es_farmacia"]] = es_fa

            # Mapear Corte Horario
            for cand in ("corte_horario", "hora_corte", "corte"):
                if cand in cols_set:
                    payload[cols_set[cand]] = corte_str

            # Mapear Unidades / Líneas / SKU si la tabla los requiere
            for cand in ("unidades_totales", "unidades", "cantidad", "cantidad_pedida", "qty"):
                if cand in cols_set:
                    payload[cols_set[cand]] = cant_val
            if "lineas" in cols_set:
                payload[cols_set["lineas"]] = int(item.get("lineas_cnt", 1))
            if "sku" in cols_set:
                payload[cols_set["sku"]] = sku_val
            if "descripcion" in cols_set:
                payload[cols_set["descripcion"]] = desc_val

            return payload

        def liberar_olas_a_terminal_rf(e=None):
            seleccionadas = [
                item for item in olas_extraidas_ns
                if (checks_liberacion.get(item["ov"]) and checks_liberacion[item["ov"]].value)
                or (item["ov"] not in checks_liberacion and item.get("seleccionada", False))
            ]
            if not seleccionadas:
                notificar("Seleccione al menos una Orden de Venta (casilla azul) para liberar a RF.", "#D97706")
                return

            corte_forzado_ui = None if dd_corte_asignar.value == "AUTO" else dd_corte_asignar.value
            liberadas_ok = 0
            lineas_insertadas_total = 0
            errores_db = []
            ovs_liberadas_set = set()

            for item in seleccionadas:
                corte_final = corte_forzado_ui or item.get("corte", "09:00")
                es_fa = bool(item.get("es_farmacia"))
                ov_final = str(item["ov"]).strip()
                if es_fa and not ov_final.upper().endswith("-FA"):
                    ov_final = f"{ov_final}-FA"

                cli_nom = str(item.get("cliente") or "CLIENTE REGISTRADO").strip()
                canal_str = "FARMACIA (-FA)" if es_fa else "ESTANDAR"
                id_ext_str = str(item.get("id_externo_ns") or item.get("ov_original") or ov_final).strip()
                if es_fa and not id_ext_str.upper().endswith("-FA"):
                    id_ext_str = f"{id_ext_str}-FA"

                fh_raw = str(item.get("fecha_hora") or "").strip()
                fecha_iso = datetime.now().isoformat()
                if fh_raw and len(fh_raw) >= 10:
                    try:
                        fecha_iso = datetime.fromisoformat(fh_raw.replace(" ", "T")).isoformat()
                    except Exception:
                        fecha_iso = datetime.now().isoformat()

                # 1. INSERTAR O RECUPERAR CABECERA EN public.netsuite_ordenes_venta
                payload_ov_exacto = {
                    "id_externo_ns": id_ext_str,
                    "numero_ov": ov_final,
                    "cliente_nombre": cli_nom,
                    "canal_venta": canal_str,
                    "fecha_emision_ns": fecha_iso,
                    "estado_ns": "PENDIENTE_PICKING",
                }

                id_ov_db = None
                try:
                    r_exist = supabase.table("netsuite_ordenes_venta").select("id").eq("numero_ov", ov_final).limit(1).execute()
                    if r_exist.data:
                        id_ov_db = r_exist.data[0].get("id")
                        supabase.table("netsuite_ordenes_venta").update(payload_ov_exacto).eq("id", id_ov_db).execute()
                    else:
                        r_ins = supabase.table("netsuite_ordenes_venta").insert(payload_ov_exacto).execute()
                        if r_ins.data:
                            id_ov_db = r_ins.data[0].get("id")
                except Exception as ex_cab:
                    try:
                        r_b1 = supabase.table("netsuite_ordenes_venta").select("id").eq("numero_ov", ov_final).limit(1).execute()
                        if r_b1.data:
                            id_ov_db = r_b1.data[0].get("id")
                        else:
                            r_b2 = supabase.table("netsuite_ordenes_venta").select("id").eq("id_externo_ns", id_ext_str).limit(1).execute()
                            if r_b2.data:
                                id_ov_db = r_b2.data[0].get("id")
                    except Exception:
                        pass
                    if id_ov_db is None:
                        errores_db.append(f"Cabecera {ov_final}: {ex_cab}")

                # 2. INSERTAR LÍNEAS EN public.netsuite_detalle_ov (Columnas exactas de tu tabla)
                lineas_det = item.get("lineas_detalle") or []
                if id_ov_db is not None and lineas_det:
                    try:
                        supabase.table("netsuite_detalle_ov").delete().eq("orden_id", id_ov_db).execute()
                    except Exception:
                        pass

                    lote_detalles = []
                    for idx_l, lin in enumerate(lineas_det, start=1):
                        sku_l = str(lin.get("sku") or "SKU").strip().upper()
                        cant_l = int(float(lin.get("cantidad") or lin.get("cantidad_pedida") or 1))
                        lote_detalles.append({
                            "orden_id": int(id_ov_db),
                            "linea_ns": int(idx_l),
                            "sku": sku_l,
                            "cantidad_pedida": cant_l,
                            "cantidad_comprometida": cant_l,
                            "cantidad_pickeada": 0,
                            "lote_asignado": "",
                            "estado_linea": "PENDIENTE",
                            "lotes_pickeados": "",
                        })

                    try:
                        supabase.table("netsuite_detalle_ov").insert(lote_detalles).execute()
                        lineas_insertadas_total += len(lote_detalles)
                    except Exception:
                        for fila_d in lote_detalles:
                            try:
                                supabase.table("netsuite_detalle_ov").insert(fila_d).execute()
                                lineas_insertadas_total += 1
                            except Exception as ex_d_ind:
                                errores_db.append(f"Detalle {ov_final} ({fila_d['sku']}): {ex_d_ind}")

                # 3. Guardar en memoria local para visualización inmediata
                ovs_liberadas_set.add(ov_final)
                registros_locales_mem[:] = [r for r in registros_locales_mem if r["ov"] != ov_final]
                registros_locales_mem.insert(
                    0,
                    {
                        "raw": payload_ov_exacto,
                        "id": id_ov_db,
                        "ov": ov_final,
                        "cliente": cli_nom,
                        "estado": "PENDIENTE_PICKING",
                        "es_farmacia": es_fa,
                        "corte": corte_final,
                        "unidades": int(item.get("unidades", 1)),
                        "unidades_pickeadas": 0,
                        "lineas_detalle": lineas_det,
                        "tabla_origen": "netsuite_ordenes_venta",
                    },
                )
                liberadas_ok += 1

            olas_extraidas_ns[:] = [it for it in olas_extraidas_ns if it["ov"] not in ovs_liberadas_set]
            cant_fa_lib = sum(1 for x in seleccionadas if x.get("es_farmacia"))
            cant_norm_lib = liberadas_ok - cant_fa_lib

            if errores_db:
                notificar(f"Aviso Supabase: {errores_db[0][:100]}", "#D97706")
            else:
                notificar(
                    f"¡{liberadas_ok} OVs y {lineas_insertadas_total} líneas guardadas en netsuite_detalle_ov! ({cant_norm_lib} Normal | {cant_fa_lib} -FA)",
                    "#047857",
                )
            renderizar_tabla_previsualizacion()
            cargar_monitor_packing_dual()

        # --- 9. COMPOSICIÓN DE PANELES Y SUB-VISTAS (ESTILO MONITOR DE RECEPCIÓN) ---
        panel_relojes_izquierdo = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("OVs capturadas por Corte Horario (Clic para filtrar)", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        [
                            crear_caja_digital(lbl_corte_09, "Corte 09:00", ACCENT_PURPLE, 88, lambda e: aplicar_filtro_corte_rapido("09:00")),
                            crear_caja_digital(lbl_corte_10, "Corte 10:00", ACCENT_PURPLE, 88, lambda e: aplicar_filtro_corte_rapido("10:00")),
                            crear_caja_digital(lbl_corte_12, "Corte 12:00", ACCENT_PURPLE, 88, lambda e: aplicar_filtro_corte_rapido("12:00")),
                            crear_caja_digital(lbl_corte_13, "Corte 13:00", ACCENT_PURPLE, 88, lambda e: aplicar_filtro_corte_rapido("13:00")),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=10),
                    ft.Text("Indicadores físicos de Olas y Estaciones de Packing", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Row(
                        [
                            crear_caja_digital(lbl_kpi_total_ovs, "Total OVs", ACCENT_TEAL, 88, lambda e: aplicar_filtro_corte_rapido("TODOS")),
                            crear_caja_digital(lbl_kpi_ov_normal, "OV Normal", ACCENT_BLUE, 88),
                            crear_caja_digital(lbl_kpi_ov_farma, "OV Farmacia", "#D97706", 88),
                            crear_caja_digital(lbl_kpi_avance_pack, "Avance Pack", "#10B981", 88),
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
                            ft.Text("Distribución de OVs por Corte Horario (09, 10, 12 y 13 hrs) y N° de OV", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            ft.Row(
                                [
                                    ft.Container(width=10, height=10, bgcolor=ACCENT_BLUE, border_radius=2),
                                    ft.Text("En Picking", size=10, color=TEXT_MUTED),
                                    ft.Container(width=10, height=10, bgcolor="#FBBF24", border_radius=2),
                                    ft.Text("Farmacia (-FA)", size=10, color=TEXT_MUTED),
                                    ft.Container(width=10, height=10, bgcolor="#10B981", border_radius=2),
                                    ft.Text("Empacado", size=10, color=TEXT_MUTED),
                                ],
                                spacing=6,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=6),
                    ft.Row(
                        [
                            ft.Container(
                                width=290,
                                height=155,
                                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                                bgcolor="#181E20",
                                border_radius=6,
                                alignment=ft.Alignment.BOTTOM_CENTER,
                                content=fila_barras_cortes,
                            ),
                            ft.Container(
                                expand=True,
                                height=155,
                                padding=8,
                                bgcolor="#181E20",
                                border_radius=6,
                                content=col_detalle_ovs_por_corte,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ],
                spacing=8,
            ),
            expand_val=True,
        )

        bloque_superior_kpi_cortes = ft.Row(
            [panel_relojes_izquierdo, panel_grafico_derecho],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        tarjeta_extraccion_netsuite = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        "PRE-VISUALIZACIÓN DE OLAS EXTRAÍDAS DESDE NETSUITE (CLASIFICADAS POR CORTE)",
                                        size=13,
                                        weight=ft.FontWeight.BOLD,
                                        color=TEXT_WHITE,
                                    ),
                                    txt_estado_erp,
                                ],
                                spacing=2,
                            ),
                            ft.Row(
                                [
                                    boton_primario("MARCAR TODAS", ft.Icons.CHECK_BOX_OUTLINED, marcar_todas_olas, "#334155", height_val=30),
                                    boton_primario("SOLO FARMACIA (-FA)", ft.Icons.MEDICAL_SERVICES_OUTLINED, marcar_solo_farmacia_olas, "#D97706", height_val=30),
                                    boton_primario("DESMARCAR TODAS", ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED, desmarcar_todas_olas, "#475569", height_val=30),
                                    boton_primario("2. LIBERAR OLAS A TERMINAL RF", ft.Icons.SEND_ROUNDED, liberar_olas_a_terminal_rf, "#047857", height_val=30),
                                ],
                                spacing=8,
                                wrap=True,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=1),
                    cont_tabla_prev_ns,
                ],
                spacing=8,
            )
        )

        fila_estaciones_packing_duales = ft.Row(
            [
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, color=ACCENT_CYAN, size=18),
                                    ft.Text(
                                        "LÍNEA DE PACKING 1: ÓRDENES DE VENTA ESTÁNDAR (OV NORMAL)",
                                        size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color=ACCENT_CYAN,
                                    ),
                                ],
                                spacing=6,
                            ),
                            ft.Divider(color=BORDER_COLOR, height=1),
                            cont_tabla_pack_norm,
                        ],
                        spacing=8,
                    ),
                    expand_val=True,
                ),
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Row(
                                        [
                                            ft.Icon(ft.Icons.MEDICAL_SERVICES_OUTLINED, color="#FBBF24", size=18),
                                            ft.Text(
                                                "LÍNEA DE PACKING 2: ÓRDENES DE VENTA FARMACIA (OV -FA)",
                                                size=12,
                                                weight=ft.FontWeight.BOLD,
                                                color="#FBBF24",
                                            ),
                                        ],
                                        spacing=6,
                                    ),
                                    boton_primario(
                                        "EXPORTAR LOTE (EXCEL + PDF)",
                                        ft.Icons.PICTURE_AS_PDF_OUTLINED,
                                        lambda e: exportar_ov_farmacia_excel_pdf(None),
                                        "#B45309",
                                        height_val=26,
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Divider(color=BORDER_COLOR, height=1),
                            cont_tabla_pack_farm,
                        ],
                        spacing=8,
                    ),
                    expand_val=True,
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        subvista_monitor_completo = ft.Column(
            [
                bloque_superior_kpi_cortes,
                tarjeta_extraccion_netsuite,
                fila_estaciones_packing_duales,
            ],
            spacing=10,
        )

        subvista_solo_extraccion = ft.Column(
            [
                bloque_superior_kpi_cortes,
                tarjeta_extraccion_netsuite,
            ],
            spacing=10,
        )

        subvista_solo_estaciones = ft.Column(
            [
                bloque_superior_kpi_cortes,
                fila_estaciones_packing_duales,
            ],
            spacing=10,
        )

        contenedor_subvista_olas = ft.Container(content=subvista_monitor_completo)

        # --- 10. BARRA SUPERIOR DE CONTROL Y TIP DE CORTE HORARIO ---
        chip_tip_horario = ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            bgcolor="#181E20",
            border_radius=6,
            border=ft.Border.all(1, "#38BDF8"),
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.ACCESS_TIME_FILLED_ROUNDED, color="#38BDF8", size=16),
                    ft.Text("TIP CORTES OFICIALES: 09:00 • 10:00 • 12:00 • 13:00 HRS  |", size=11, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    lbl_tip_corte,
                ],
                spacing=6,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
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
                                    ft.Icon(ft.Icons.VIEW_IN_AR_OUTLINED, color=ACCENT_CYAN, size=22),
                                    ft.Text(
                                        "KPI OLAS DE PICKING & ESTACIONES DE PACKING (NORMAL / -FA)",
                                        size=15,
                                        weight=ft.FontWeight.W_900,
                                        color=TEXT_WHITE,
                                    ),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Row(
                                [
                                    txt_fecha_desde,
                                    txt_fecha_hasta,
                                    dd_corte_asignar,
                                    dd_filtro_corte,
                                    boton_primario("1. EXTRAER ORDENES NETSUITE", ft.Icons.CLOUD_DOWNLOAD_OUTLINED, extraer_ordenes_netsuite, ACCENT_BLUE),
                                    ft.IconButton(
                                        icon=ft.Icons.SYNC_ROUNDED,
                                        icon_color=ACCENT_CYAN,
                                        tooltip="Refrescar Estaciones de Packing y Cortes",
                                        on_click=cargar_monitor_packing_dual,
                                    ),
                                ],
                                spacing=8,
                                wrap=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    chip_tip_horario,
                ],
                spacing=8,
            ),
        )

        col_principal_picking = ft.Column(
            [
                barra_titulo_monitor,
                contenedor_subvista_olas,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self.vista = ft.Container(padding=14, bgcolor=BG_MODULO, content=col_principal_picking, expand=True)
        self.contenedor = contenedor_subvista_olas
        self.sub_completo = subvista_monitor_completo
        self.sub_extraccion = subvista_solo_extraccion
        self.sub_estaciones = subvista_solo_estaciones
        self.cargar_monitor_packing_dual_func = cargar_monitor_packing_dual

    def cargar_monitor_packing_dual(self, e=None):
        self.cargar_monitor_packing_dual_func(e)

    def sel_sub_olas(self, idx: int):
        self.contenedor.content = [
            self.sub_completo,
            self.sub_extraccion,
            self.sub_estaciones,
        ][idx]
        self.cargar_monitor_packing_dual_func()
        self.page.update()