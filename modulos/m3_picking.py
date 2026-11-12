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

        # --- 1. CONSTANTES DE DISEÑO OSCURO ---
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
        olas_extraidas_ns = []
        checks_liberacion = {}
        checks_facturacion = {}
        registros_packing_db = []
        registros_locales_mem = []
        filtro_corte_activo = "TODOS"
        esquemas_tablas_sb = {}
        modo_columnas_packing = {"apilado": True}
        Archivo_Meta_Despacho = "config_despacho_packing.json"

        def cargar_meta_despacho() -> dict:
            if os.path.exists(Archivo_Meta_Despacho):
                try:
                    with open(Archivo_Meta_Despacho, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    return {}
            return {}

        def guardar_meta_despacho(ov_key: str, datos: dict):
            mapa = cargar_meta_despacho()
            mapa[str(ov_key).strip().upper()] = datos
            try:
                with open(Archivo_Meta_Despacho, "w", encoding="utf-8") as f:
                    json.dump(mapa, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        def boton_primario(texto: str, icono, on_click, color_bg: str, height_val: int = 32, width_val=None):
            def animar_hover(e):
                e.control.opacity = 0.85 if e.data == "true" else 1.0
                e.control.update()

            return ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(icono, color=TEXT_WHITE, size=14),
                        ft.Text(texto, size=10.5, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ],
                    spacing=5,
                    alignment=ft.MainAxisAlignment.CENTER,
                    tight=True,
                ),
                bgcolor=color_bg,
                padding=ft.Padding.symmetric(horizontal=10, vertical=0),
                height=height_val,
                width=width_val,
                border_radius=6,
                ink=True,
                on_click=on_click,
                on_hover=animar_hover,
            )

        def notificar(texto: str, color: str = "#0284C7"):
            from dependencias import notificar_global
            notificar_global(self.page, texto, color)
            
        def descargar_archivo_web(ruta_archivo: str, titulo_doc: str = "Documento Generado"):
            """Publica el Excel/PDF en /descargas/, lanza descarga automática y muestra ventana con botón directo."""
            import shutil
            import inspect
            import urllib.parse

            if not ruta_archivo or not os.path.exists(ruta_archivo):
                notificar("No se encontró el archivo generado en el servidor.", "#B91C1C")
                return
            try:
                nombre_orig = os.path.basename(ruta_archivo)
                base_nom, ext_nom = os.path.splitext(nombre_orig)
                limpio = "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in str(base_nom))
                nombre_seguro = f"{limpio[:45] or 'DOC'}{ext_nom.lower()}"

                raiz_proyecto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                for carpeta_d in (
                    os.path.join(os.getcwd(), "assets", "descargas"),
                    os.path.join(raiz_proyecto, "assets", "descargas"),
                ):
                    try:
                        os.makedirs(carpeta_d, exist_ok=True)
                        dest_f = os.path.join(carpeta_d, nombre_seguro)
                        if os.path.abspath(ruta_archivo) != os.path.abspath(dest_f):
                            shutil.copy2(ruta_archivo, dest_f)
                    except Exception:
                        pass

                url_descarga = f"/descargas/{urllib.parse.quote(nombre_seguro)}"

                async def _lanzar_url():
                    try:
                        res = self.page.launch_url(url_descarga, web_popup_window_name="_blank")
                        if inspect.iscoroutine(res):
                            await res
                    except Exception:
                        try:
                            res2 = self.page.launch_url(url_descarga)
                            if inspect.iscoroutine(res2):
                                await res2
                        except Exception:
                            pass

                try:
                    self.page.run_task(_lanzar_url)
                except Exception:
                    pass

                def _cerrar_dlg_dl(ev=None):
                    try:
                        self.page.pop_dialog()
                    except Exception:
                        dlg_dl.open = False
                    self.page.update()

                dlg_dl = ft.AlertDialog(
                    modal=False,
                    bgcolor="#1E293B",
                    title=ft.Row(
                        [
                            ft.Icon(ft.Icons.CLOUD_DOWNLOAD_ROUNDED, color="#34D399", size=24),
                            ft.Text(titulo_doc, size=15, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                        ],
                        spacing=8,
                    ),
                    content=ft.Column(
                        [
                            ft.Text(f"Archivo listo: {nombre_seguro}", size=12, color=ACCENT_CYAN, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "Haga clic en el botón verde para guardar el archivo en su computador:",
                                size=11,
                                color=TEXT_MUTED,
                            ),
                        ],
                        spacing=6,
                        tight=True,
                    ),
                    actions=[
                        ft.TextButton("CERRAR", on_click=_cerrar_dlg_dl),
                        ft.Button(
                            content=ft.Text("DESCARGAR ARCHIVO AHORA", size=12, weight=ft.FontWeight.BOLD),
                            icon=ft.Icons.DOWNLOAD_ROUNDED,
                            bgcolor="#047857",
                            color=ft.Colors.WHITE,
                            url=url_descarga,
                        ),
                    ],
                )
                self.page.show_dialog(dlg_dl)
                self.page.update()
            except Exception as ex_dl:
                notificar(f"Error preparando descarga web: {ex_dl}", "#B91C1C")    

        def tarjeta_dark(contenido, padding=12, expand_val=None, height_val=None, width_val=None):
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

        def envolver_tabla_fluida(tabla: ft.DataTable, altura_max: int):
            return ft.Container(
                height=altura_max,
                padding=ft.Padding.only(right=10, bottom=4),
                bgcolor="#181E20",
                border_radius=6,
                border=ft.Border.all(1, BORDER_COLOR),
                content=ft.Column(
                    [
                        ft.Row(
                            [tabla],
                            scroll=ft.ScrollMode.ALWAYS,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        )
                    ],
                    scroll=ft.ScrollMode.ALWAYS,
                    expand=True,
                ),
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

        def crear_caja_digital(txt_control: ft.Text, etiqueta_inf: str, color_borde: str = "#6366F1", ancho: int = 82, on_click=None):
            return ft.Column(
                [
                    ft.Container(
                        width=ancho,
                        height=54,
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
                spacing=3,
            )

        # --- 4. CLASIFICADOR DE CORTE HORARIO ---
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
        txt_fecha_desde = texto_dark(label="Fecha Desde (YYYY-MM-DD)", value=hoy_str, width=150)
        txt_fecha_hasta = texto_dark(label="Fecha Hasta (YYYY-MM-DD)", value=hoy_str, width=150)

        dd_corte_asignar = dropdown_dark(
            label="Corte al Liberar Ola",
            width=155,
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
            width=175,
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

        lbl_corte_09 = ft.Text("00", size=22, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_corte_10 = ft.Text("00", size=22, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_corte_12 = ft.Text("00", size=22, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_corte_13 = ft.Text("00", size=22, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")

        lbl_kpi_total_ovs = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color=TEXT_WHITE, font_family="Consolas")
        lbl_kpi_ov_normal = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color="#38BDF8", font_family="Consolas")
        lbl_kpi_ov_farma = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color="#FBBF24", font_family="Consolas")
        lbl_kpi_pend_fact = ft.Text("0", size=17, weight=ft.FontWeight.W_900, color="#34D399", font_family="Consolas")

        fila_barras_cortes = ft.Row(
            spacing=14,
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
            vertical_alignment=ft.CrossAxisAlignment.END,
        )
        col_detalle_ovs_por_corte = ft.Column(spacing=6, scroll=ft.ScrollMode.ALWAYS, expand=True)

        # --- 6. TABLAS EN MODO OSCURO ---
        tabla_previsualizacion_ns = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=32,
            data_row_min_height=30,
            data_row_max_height=36,
            column_spacing=14,
            horizontal_margin=10,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("LIBERAR", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("ORDEN DE VENTA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("FECHA OV", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
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
            heading_row_height=32,
            data_row_min_height=32,
            data_row_max_height=38,
            column_spacing=14,
            horizontal_margin=10,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("OV ESTÁNDAR", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("FECHA OV", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("CORTE", weight=ft.FontWeight.BOLD, size=10, color="#A78BFA")),
                ft.DataColumn(ft.Text("CLIENTE", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ESTADO OPERATIVO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIONES DE PACKING Y CIERRE A FACTURACIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        tabla_packing_farmacia = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=32,
            data_row_min_height=32,
            data_row_max_height=38,
            column_spacing=14,
            horizontal_margin=10,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("OV FARMACIA (-FA)", weight=ft.FontWeight.BOLD, size=10, color="#FBBF24")),
                ft.DataColumn(ft.Text("FECHA OV", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("CORTE", weight=ft.FontWeight.BOLD, size=10, color="#A78BFA")),
                ft.DataColumn(ft.Text("CLIENTE", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ESTADO OPERATIVO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIONES DE PACKING Y CIERRE A FACTURACIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        # TABLA DEL NUEVO MÓDULO 4: FACTURACIÓN (OVs en PENDIENTE_FACTURACION)
        txt_buscar_facturacion = texto_dark(label="Buscar por N° OV, Cliente, Comuna o LPN...", width=280)
        sw_ver_ya_facturadas = ft.Switch(label="Ver también Facturadas", value=False, active_color="#10B981")
        lbl_resumen_facturacion = ft.Text(
            "0 OVs listas en Pendiente de Facturación para subir a NetSuite.",
            size=12,
            weight=ft.FontWeight.BOLD,
            color="#34D399",
        )

        tabla_facturacion_ns = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=34,
            data_row_max_height=40,
            column_spacing=14,
            horizontal_margin=10,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("SEL.", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("OV / OT", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("FECHA", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("CANAL", weight=ft.FontWeight.BOLD, size=10, color="#FBBF24")),
                ft.DataColumn(ft.Text("CLIENTE", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("COMUNA DESPACHO", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("EMPAQUE / BULTOS", weight=ft.FontWeight.BOLD, size=10, color="#A78BFA")),
                ft.DataColumn(ft.Text("UNID. EMPACADAS", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("ESTADO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("DOCUMENTOS Y ACCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        cont_tabla_prev_ns = envolver_tabla_fluida(tabla_previsualizacion_ns, 220)
        cont_tabla_pack_norm = envolver_tabla_fluida(tabla_packing_normal, 250)
        cont_tabla_pack_farm = envolver_tabla_fluida(tabla_packing_farmacia, 250)
        cont_tabla_facturacion = envolver_tabla_fluida(tabla_facturacion_ns, 360)

        # --- 7. CONEXIÓN Y SINCRONIZACIÓN CON SUPABASE ---
        def detectar_es_farmacia_texto(*textos) -> bool:
            for t in textos:
                s = str(t or "").strip().upper()
                if not s:
                    continue
                if "-FA" in s or s.endswith("FA") or "BOEHRINGER" in s or "PICK-FARM" in s or "FARMACIA" in s:
                    return True
            return False

        def extraer_campos_registro_ola(r: dict, mapa_clientes_ns: dict = None, mapa_meta_desp: dict = None) -> dict:
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

            # Homologar el estado antiguo EMPACADO a PENDIENTE_FACTURACION para el nuevo flujo
            if est_val in ("EMPACADO", "COMPLETADO"):
                est_val = "PENDIENTE_FACTURACION"

            canal_val = str(r.get("canal_venta") or r.get("tipo_ola") or r.get("canal") or "").strip().upper()

            es_fa = (
                bool(r.get("es_farmacia"))
                or detectar_es_farmacia_texto(ov_val, canal_val, r.get("sku"), r.get("descripcion"))
            )
            if es_fa and not ov_val.endswith("-FA") and not ov_val.startswith("OT-"):
                ov_val = f"{ov_val}-FA"

            ts_val = (
                r.get("corte_horario")
                or r.get("hora_corte")
                or r.get("corte")
                or r.get("fecha_emision_ns")
                or r.get("created_at")
            )
            corte_str = clasificar_corte_horario(ts_val) if ts_val else clasificar_corte_horario(None)

            raw_fecha_ov = str(r.get("fecha_emision_ns") or r.get("fecha_ov") or r.get("created_at") or "").strip()
            fecha_ov_str = raw_fecha_ov[:10] if len(raw_fecha_ov) >= 10 else datetime.now().strftime("%Y-%m-%d")

            try:
                unid_val = int(float(r.get("unidades") or r.get("unidades_totales") or r.get("total_unidades") or r.get("cantidad") or 1))
            except Exception:
                unid_val = 1

            meta_ov = (mapa_meta_desp or {}).get(ov_val) or (mapa_meta_desp or {}).get(ov_limpia) or {}
            comuna_str = str(r.get("comuna") or meta_ov.get("comuna") or ("CONCEPCIÓN" if "CONCEPCION" in cli_val.upper() else "SANTIAGO")).strip().upper()
            tipo_emp_str = str(meta_ov.get("tipo_empaque") or "BULTO").strip().upper()
            bultos_cnt = int(meta_ov.get("bultos") or 1)
            lpn_str = str(meta_ov.get("lpn") or f"LPN-PK-{ov_limpia}").strip().upper()

            return {
                "raw": r,
                "id": r.get("id"),
                "ov": ov_val,
                "fecha_ov": fecha_ov_str,
                "cliente": cli_val,
                "comuna": comuna_str,
                "tipo_empaque": tipo_emp_str,
                "bultos": bultos_cnt,
                "lpn": lpn_str,
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
            mapa_meta_desp = cargar_meta_despacho()

            mapa_maestra_sku = {}
            try:
                res_m = supabase.table("maestra_sku").select("*").limit(5000).execute()
                for m in (res_m.data or []):
                    s_k = str(m.get("sku") or "").strip().upper()
                    if not s_k:
                        continue
                    ean_val = (
                        m.get("codigo_barras")
                        or m.get("ean")
                        or m.get("ean_base")
                        or m.get("gtin")
                        or m.get("barcode")
                        or m.get("upc")
                        or ""
                    )
                    info_sku_m = {
                        "descripcion": str(m.get("descripcion") or m.get("nombre") or "").strip(),
                        "ean": str(ean_val or "").strip(),
                        "marca": str(m.get("marca") or "").strip(),
                    }
                    mapa_maestra_sku[s_k] = info_sku_m
                    s_base = s_k.split("-")[0].strip()
                    if s_base and s_base not in mapa_maestra_sku:
                        mapa_maestra_sku[s_base] = info_sku_m
            except Exception:
                pass

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

            mapa_id_a_ov = {}
            bodega_act = obtener_bodega_activa(self.page)
            try:
                res_ov = supabase.table("netsuite_ordenes_venta").select("*").order("id", desc=True).limit(500).execute()
                filas_ov = [
                    r for r in (res_ov.data or [])
                    if coincide_bodega(r, bodega_act)
                ]
                for r in filas_ov:
                    r_copia = dict(r)
                    r_copia["_tabla_origen"] = "netsuite_ordenes_venta"
                    info = extraer_campos_registro_ola(r_copia, mapa_clientes_ns, mapa_meta_desp)
                    if not info:
                        continue
                    ov_k = info["ov"]
                    if r.get("id") is not None:
                        mapa_id_a_ov[r.get("id")] = ov_k
                    agrupado_por_ov[ov_k] = info
            except Exception:
                pass

            mapa_lineas_pl_por_ov = {}
            try:
                res_pl = supabase.table("wms_packing_lists_fa").select("*").order("id", desc=True).limit(300).execute()
                for pl in (res_pl.data or []):
                    if not coincide_bodega(pl, bodega_act):
                        continue
                    ov_pl_raw = str(pl.get("numero_ov") or "").strip().upper()
                    if not ov_pl_raw:
                        continue
                    ov_pl = ov_pl_raw.split("(")[0].split("|")[0].strip()
                    if not ov_pl.endswith("-FA") and not ov_pl.startswith("OT-") and ov_pl not in agrupado_por_ov:
                        if f"{ov_pl}-FA" in agrupado_por_ov:
                            ov_pl = f"{ov_pl}-FA"

                    det_json = pl.get("detalle_json")
                    if isinstance(det_json, str):
                        try:
                            det_json = json.loads(det_json)
                        except Exception:
                            det_json = []

                    lineas_pl = []
                    meta_desde_json = {}
                    if isinstance(det_json, list):
                        for item_j in det_json:
                            if isinstance(item_j, dict):
                                if item_j.get("comuna") or item_j.get("bultos") or item_j.get("lpn_consolidado"):
                                    meta_desde_json = {
                                        "comuna": item_j.get("comuna"),
                                        "tipo_empaque": item_j.get("tipo_empaque"),
                                        "bultos": item_j.get("bultos"),
                                        "lpn": item_j.get("lpn_consolidado"),
                                    }
                                sku_j = str(item_j.get("sku") or "").strip().upper()
                                if not sku_j:
                                    continue
                                sku_j_base = sku_j.split("-")[0].strip()
                                inf_m = mapa_maestra_sku.get(sku_j) or mapa_maestra_sku.get(sku_j_base) or {}
                                lineas_pl.append({
                                    "sku": sku_j,
                                    "ean": str(item_j.get("ean") or inf_m.get("ean") or "").strip(),
                                    "descripcion": str(item_j.get("descripcion") or inf_m.get("descripcion") or "").strip(),
                                    "cantidad": int(float(item_j.get("solicitado") or 0)),
                                    "cantidad_pedida": int(float(item_j.get("solicitado") or 0)),
                                    "cantidad_pickeada": int(float(item_j.get("pickeado") or 0)),
                                    "lotes": str(item_j.get("lotes") or "").strip(),
                                    "es_farmacia": True,
                                })

                    if lineas_pl and ov_pl not in mapa_lineas_pl_por_ov:
                        mapa_lineas_pl_por_ov[ov_pl] = lineas_pl

                    if ov_pl in agrupado_por_ov and meta_desde_json:
                        if meta_desde_json.get("comuna"):
                            agrupado_por_ov[ov_pl]["comuna"] = str(meta_desde_json["comuna"]).upper()
                        if meta_desde_json.get("tipo_empaque"):
                            agrupado_por_ov[ov_pl]["tipo_empaque"] = str(meta_desde_json["tipo_empaque"]).upper()
                        if meta_desde_json.get("bultos"):
                            agrupado_por_ov[ov_pl]["bultos"] = int(meta_desde_json["bultos"])
                        if meta_desde_json.get("lpn"):
                            agrupado_por_ov[ov_pl]["lpn"] = str(meta_desde_json["lpn"]).upper()
            except Exception:
                pass

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
                    sku_d_base = sku_d.split("-")[0].strip()
                    info_m = mapa_maestra_sku.get(sku_d) or mapa_maestra_sku.get(sku_d_base) or {}

                    respaldo_pl = next(
                        (
                            x for x in mapa_lineas_pl_por_ov.get(ov_d, [])
                            if x["sku"] == sku_d or x["sku"].split("-")[0].strip() == sku_d_base
                        ),
                        {},
                    )

                    desc_d = str(d.get("descripcion") or info_m.get("descripcion") or respaldo_pl.get("descripcion") or "").strip()
                    ean_d = str(d.get("ean") or info_m.get("ean") or respaldo_pl.get("ean") or "").strip()
                    cant_ped = int(float(d.get("cantidad_pedida") or d.get("cantidad_comprometida") or respaldo_pl.get("cantidad_pedida") or 0))
                    cant_pick_db = int(float(d.get("cantidad_pickeada") or 0))
                    cant_pick_pl = int(float(respaldo_pl.get("cantidad_pickeada") or 0))
                    cant_pick = max(cant_pick_db, cant_pick_pl)

                    lotes_d = str(d.get("lotes_pickeados") or d.get("lote_asignado") or "").strip()
                    if lotes_d.upper() in ("NONE", "NULL", ""):
                        lotes_d = str(respaldo_pl.get("lotes") or "").strip()

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
                        "estado_linea": str(d.get("estado_linea") or ("COMPLETADO" if cant_pick >= cant_ped and cant_ped > 0 else "PENDIENTE")).upper(),
                        "es_farmacia": agrupado_por_ov[ov_d].get("es_farmacia", False),
                    })

                for ov_c in ovs_con_detalle_db:
                    lins = agrupado_por_ov[ov_c]["lineas_detalle"]
                    agrupado_por_ov[ov_c]["unidades"] = sum(x.get("cantidad_pedida", 0) for x in lins)
                    agrupado_por_ov[ov_c]["unidades_pickeadas"] = sum(x.get("cantidad_pickeada", 0) for x in lins)
            except Exception as ex_d:
                print(f"[WARN] Error leyendo netsuite_detalle_ov: {ex_d}")

            for item_mem in registros_locales_mem:
                ov_m = item_mem["ov"]
                if ov_m not in agrupado_por_ov:
                    agrupado_por_ov[ov_m] = item_mem
                else:
                    item_mem["estado"] = agrupado_por_ov[ov_m]["estado"]
                    if agrupado_por_ov[ov_m].get("lineas_detalle"):
                        item_mem["lineas_detalle"] = agrupado_por_ov[ov_m]["lineas_detalle"]

            registros_packing_db = list(agrupado_por_ov.values())

        def cambiar_filtro_estado_interno(corte_sel: str):
            nonlocal filtro_corte_activo
            if filtro_corte_activo == corte_sel:
                filtro_corte_activo = "TODOS"
            else:
                filtro_corte_activo = corte_sel
            dd_filtro_corte.value = filtro_corte_activo

        def construir_barra_corte(etiqueta_corte: str, cant_ovs: int, cant_listas: int, max_escala: int, fn_click_corte=None):
            altura_max_px = 86
            ratio = min(1.0, cant_ovs / max(1, max_escala))
            alto_barra = max(12, int(ratio * altura_max_px)) if cant_ovs > 0 else 6
            es_completo = cant_ovs > 0 and cant_listas >= cant_ovs
            color_b = "#10B981" if es_completo else (ACCENT_BLUE if cant_ovs > 0 else "#334155")

            return ft.Column(
                [
                    ft.Text(f"{cant_ovs} OV", size=10, color=TEXT_WHITE, weight=ft.FontWeight.BOLD),
                    ft.Container(
                        width=38,
                        height=altura_max_px,
                        bgcolor="#141A1C",
                        border_radius=4,
                        alignment=ft.Alignment.BOTTOM_CENTER,
                        ink=True,
                        on_click=fn_click_corte,
                        tooltip=f"Corte {etiqueta_corte}: {cant_ovs} OVs ({cant_listas} en Facturación) - Clic para filtrar",
                        content=ft.Container(
                            width=38,
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

        def cambiar_estado_ov_db(info_item: dict, nuevo_estado: str):
            ov_cod = str(info_item.get("ov") or "").strip().upper()
            ov_sin_fa = ov_cod.removesuffix("-FA").strip()
            info_item["estado"] = nuevo_estado
            for m_it in registros_locales_mem:
                if m_it["ov"] in (ov_cod, ov_sin_fa):
                    m_it["estado"] = nuevo_estado

            for col_ov in ("estado_ns", "estado"):
                try:
                    supabase.table("netsuite_ordenes_venta").update({col_ov: nuevo_estado}).or_(
                        f"numero_ov.eq.{ov_cod},numero_ov.eq.{ov_sin_fa}"
                    ).execute()
                    break
                except Exception:
                    continue

        def imprimir_etiqueta_packing_bultos_ov(info_ov: dict):
            ov_cod = str(info_ov.get("ov") or "S/OV").strip().upper()
            ov_limpia = ov_cod.removesuffix("-FA").strip()
            meta_ov = cargar_meta_despacho().get(ov_cod) or cargar_meta_despacho().get(ov_limpia) or {}

            lpn_usar = str(meta_ov.get("lpn") or info_ov.get("lpn") or f"LPN-PK-{ov_limpia}").strip().upper()
            cli_usar = str(info_ov.get("cliente") or "SIN CLIENTE").strip().upper()
            comuna_usar = str(meta_ov.get("comuna") or info_ov.get("comuna") or "SANTIAGO").strip().upper()
            tipo_usar = str(meta_ov.get("tipo_empaque") or info_ov.get("tipo_empaque") or "BULTO").strip().upper()
            bultos_usar = int(meta_ov.get("bultos") or info_ov.get("bultos") or 1)

            try:
                ruta_pdf = generar_pdf_etiqueta_packing_bultos_15x10(
                    lpn=lpn_usar,
                    numero_ov=ov_cod,
                    cliente=cli_usar,
                    comuna=comuna_usar,
                    tipo_empaque=tipo_usar,
                    total_bultos=bultos_usar,
                )
                descargar_archivo_web(ruta_pdf, f"Etiquetas 15x10 ({bultos_usar} {tipo_usar}) - OV {ov_cod}")
            except Exception as ex:
                notificar(f"Error generando etiquetas de bultos: {ex}", "#B91C1C")

        def abrir_modal_empaque_y_pasar_a_facturacion(info_ov: dict):
            """Abre el asistente de Packing para definir Comuna, Bulto/Pallet y Cantidad (1 de N), imprime etiquetas y pasa a Facturación."""
            ov_cod = str(info_ov.get("ov") or "").strip().upper()
            ov_limpia = ov_cod.removesuffix("-FA").strip()
            cli_str = str(info_ov.get("cliente") or "SIN CLIENTE").strip()
            meta_prev = cargar_meta_despacho().get(ov_cod) or cargar_meta_despacho().get(ov_limpia) or {}

            lpn_default = str(meta_prev.get("lpn") or info_ov.get("lpn") or f"LPN-PK-{ov_limpia}-{datetime.now().strftime('%H%M')}").upper()
            comuna_default = str(meta_prev.get("comuna") or info_ov.get("comuna") or ("CONCEPCIÓN" if "CONCEPCION" in cli_str.upper() else "SANTIAGO")).upper()
            tipo_default = str(meta_prev.get("tipo_empaque") or info_ov.get("tipo_empaque") or "BULTO").upper()
            bultos_default = str(meta_prev.get("bultos") or info_ov.get("bultos") or 1)

            txt_lpn_pk = texto_dark("LPN de Despacho", width=220, value=lpn_default)
            txt_comuna_pk = texto_dark("Comuna de Despacho", width=240, value=comuna_default)
            dd_tipo_pk = dropdown_dark(
                "Modalidad de Despacho",
                width=220,
                value=tipo_default if tipo_default in ("BULTO", "PALLET") else "BULTO",
                options=[
                    opt_w("BULTO", "POR BULTO / CAJA"),
                    opt_w("PALLET", "POR PALLET"),
                ],
            )
            txt_cant_bultos_pk = texto_dark(
                "Cantidad de Bultos / Pallets (Ej: 3 -> 1 de 3, 2 de 3, 3 de 3)",
                width=240,
                value=bultos_default,
                keyboard_type=ft.KeyboardType.NUMBER,
            )

            def cerrar_m(ev=None):
                try:
                    page.pop_dialog()
                except Exception:
                    dlg_pack.open = False
                page.update()

            def confirmar_cierre_packing(ev=None):
                comuna_f = (txt_comuna_pk.value or "SANTIAGO").strip().upper()
                tipo_f = (dd_tipo_pk.value or "BULTO").strip().upper()
                lpn_f = (txt_lpn_pk.value or f"LPN-PK-{ov_limpia}").strip().upper()
                try:
                    cant_b = max(1, int((txt_cant_bultos_pk.value or "1").strip()))
                except Exception:
                    cant_b = 1

                datos_meta = {
                    "lpn": lpn_f,
                    "comuna": comuna_f,
                    "tipo_empaque": tipo_f,
                    "bultos": cant_b,
                    "fecha_packing": datetime.now().strftime("%d-%m-%Y %H:%M"),
                }
                guardar_meta_despacho(ov_cod, datos_meta)
                guardar_meta_despacho(ov_limpia, datos_meta)

                info_ov["comuna"] = comuna_f
                info_ov["tipo_empaque"] = tipo_f
                info_ov["bultos"] = cant_b
                info_ov["lpn"] = lpn_f

                cerrar_m()

                # 1. Cambiar estado a PENDIENTE_FACTURACION (desaparece de Picking/Packing y pasa a Facturación)
                cambiar_estado_ov_db(info_ov, "PENDIENTE_FACTURACION")

                # 2. Emitir etiquetas 15x10 por cada bulto/pallet (1 de N, 2 de N...)
                try:
                    ruta_etq = generar_pdf_etiqueta_packing_bultos_15x10(
                        lpn=lpn_f,
                        numero_ov=ov_cod,
                        cliente=cli_str,
                        comuna=comuna_f,
                        tipo_empaque=tipo_f,
                        total_bultos=cant_b,
                    )
                    descargar_archivo_web(ruta_etq, f"Etiquetas 15x10 - OV {ov_cod}")
                except Exception as ex_p:
                    print(f"[WARN] Error generando PDF bultos: {ex_p}")

                
                recargar_datos_supabase()
                renderizar_monitor_cortes_y_tablas()

            dlg_pack = ft.AlertDialog(
                modal=True,
                bgcolor="#1E293B",
                title=ft.Row(
                    [
                        ft.Icon(ft.Icons.INVENTORY_ROUNDED, color=ACCENT_CYAN, size=22),
                        ft.Text(f"Cerrar Packing y Emitir Etiquetas (OV {ov_cod})", size=15, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ],
                    spacing=8,
                ),
                content=ft.Container(
                    width=520,
                    content=ft.Column(
                        [
                            ft.Container(
                                padding=10,
                                bgcolor="#0F172A",
                                border_radius=6,
                                content=ft.Column(
                                    [
                                        ft.Text(f"CLIENTE: {cli_str}", size=12, weight=ft.FontWeight.BOLD, color="#34D399"),
                                        ft.Text(
                                            "Al confirmar, se imprimirán las etiquetas 15x10 (1 de N) con OV, Cliente, Comuna y Bultos, y la OV pasará a PENDIENTE DE FACTURACIÓN.",
                                            size=11,
                                            color=TEXT_MUTED,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            ft.Row([txt_lpn_pk, txt_comuna_pk], spacing=10, wrap=True),
                            ft.Row([dd_tipo_pk, txt_cant_bultos_pk], spacing=10, wrap=True),
                        ],
                        spacing=10,
                        tight=True,
                    ),
                ),
                actions=[
                    ft.TextButton("CANCELAR", on_click=cerrar_m),
                    boton_primario(
                        "CONFIRMAR PACKING -> PASAR A FACTURACIÓN + ETIQUETAS 15x10",
                        ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                        confirmar_cierre_packing,
                        "#047857",
                        height_val=36,
                    ),
                ],
            )
            page.show_dialog(dlg_pack)
            page.update()

        def mostrar_modal_detalle_ov(ov_num: str, info_ov: dict):
            lineas_det = info_ov.get("lineas_detalle", [])
            filas_d = []
            for ld in lineas_det:
                es_sku_fa = ld.get("es_farmacia", False)
                cant_sol = int(ld.get("cantidad_pedida") or ld.get("cantidad") or 0)
                cant_pk = int(ld.get("cantidad_pickeada") or 0)
                lotes_str = str(ld.get("lotes") or "").strip()
                txt_cant = f"{cant_pk}/{cant_sol} UN" if cant_pk > 0 else f"{cant_sol} UN"
                sub_lote = f"  • Lotes: {lotes_str}" if lotes_str else ""

                filas_d.append(
                    ft.Row(
                        [
                            ft.Text(str(ld.get("sku", "-")), size=11, weight=ft.FontWeight.BOLD, color="#FBBF24" if es_sku_fa else ACCENT_CYAN, width=110),
                            ft.Text(f"{str(ld.get('descripcion', '-'))[:34]}{sub_lote}", size=11, color=TEXT_WHITE, expand=True),
                            ft.Text(txt_cant, size=11, weight=ft.FontWeight.BOLD, color="#34D399"),
                        ],
                        spacing=8,
                    )
                )
            if not filas_d:
                filas_d.append(ft.Text(f"Cliente: {info_ov.get('cliente', '-')}", size=12, color=TEXT_WHITE))
                filas_d.append(ft.Text(f"Comuna: {info_ov.get('comuna', 'SANTIAGO')}", size=12, color=ACCENT_CYAN))
                filas_d.append(ft.Text(f"Estado Actual: {info_ov.get('estado', '-')}", size=12, color="#34D399"))

            def cerrar_d(ev=None):
                try:
                    page.pop_dialog()
                except Exception:
                    dlg_det.open = False
                page.update()

            dlg_det = ft.AlertDialog(
                title=ft.Text(
                    f"Detalle Orden #{ov_num} | {info_ov.get('cliente', '')[:30]}",
                    color=TEXT_WHITE,
                    size=15,
                    weight=ft.FontWeight.BOLD,
                ),
                bgcolor=BG_CARD,
                content=ft.Container(
                    width=560,
                    height=260,
                    padding=10,
                    bgcolor="#181E20",
                    border_radius=6,
                    content=ft.Column(filas_d, spacing=6, scroll=ft.ScrollMode.ALWAYS),
                ),
                actions=[
                    boton_primario(
                        "ETIQUETA BULTOS (15x10)",
                        ft.Icons.QR_CODE_2_ROUNDED,
                        lambda ev: imprimir_etiqueta_packing_bultos_ov(info_ov),
                        ACCENT_TEAL,
                        height_val=32,
                    ),
                    boton_primario(
                        "PACKING LIST (PDF + EXCEL)",
                        ft.Icons.PICTURE_AS_PDF_OUTLINED,
                        lambda ev: exportar_ov_farmacia_excel_pdf(info_ov),
                        "#B45309",
                        height_val=32,
                    ),
                    ft.TextButton("Cerrar", on_click=cerrar_d),
                ],
            )
            page.show_dialog(dlg_det)
            page.update()

        def exportar_excel_facturacion_netsuite(e=None, solo_ov: dict = None):
            """Genera y descarga en el navegador el Excel (.xlsx) para subir a NetSuite y facturar."""
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment

            if solo_ov:
                lista_fact = [solo_ov]
            else:
                seleccionadas_chk = [
                    reg for _, (chk, reg) in checks_facturacion.items() if chk.value
                ]
                if seleccionadas_chk:
                    lista_fact = seleccionadas_chk
                else:
                    lista_fact = [
                        r for r in registros_packing_db
                        if r.get("estado") == "PENDIENTE_FACTURACION"
                    ]

            if not lista_fact:
                notificar("No hay OVs en estado PENDIENTE_FACTURACION seleccionadas para exportar.", "#D97706")
                return

            try:
                os.makedirs("reportes_facturacion", exist_ok=True)
                ts_now = datetime.now().strftime("%Y%m%d_%H%M%S")
                suf_ov = str(solo_ov.get("ov", "")).strip() if solo_ov else "LOTE"
                ruta_xlsx = os.path.join("reportes_facturacion", f"NetSuite_Facturacion_{suf_ov}_{ts_now}.xlsx")

                filas_detalle_ns = []
                filas_resumen_ov = []
                ovs_procesadas_excel = set()

                for ov_item in lista_fact:
                    ov_cod = str(ov_item.get("ov") or "").strip().upper()
                    ov_limpia = ov_cod.removesuffix("-FA").strip()
                    if ov_limpia in ovs_procesadas_excel:
                        continue
                    ovs_procesadas_excel.add(ov_limpia)

                    fecha_ov = str(ov_item.get("fecha_ov") or datetime.now().strftime("%Y-%m-%d"))
                    cli_nom = str(ov_item.get("cliente") or "CLIENTE").strip()
                    comuna_nom = str(ov_item.get("comuna") or "SANTIAGO").strip()
                    tipo_emp = str(ov_item.get("tipo_empaque") or "BULTO").strip()
                    cant_bultos = int(ov_item.get("bultos") or 1)
                    lpn_cod = str(ov_item.get("lpn") or f"LPN-PK-{ov_limpia}").strip()
                    canal_str = "FARMACIA (-FA)" if ov_item.get("es_farmacia") else "ESTANDAR"

                    lineas = list(ov_item.get("lineas_detalle") or [])
                    if not lineas and ov_item.get("id") is not None:
                        try:
                            r_det = supabase.table("netsuite_detalle_ov").select("*").eq("orden_id", ov_item["id"]).order("linea_ns").execute()
                            for d in (r_det.data or []):
                                lineas.append({
                                    "linea_ns": d.get("linea_ns"),
                                    "sku": str(d.get("sku") or "").strip().upper(),
                                    "descripcion": str(d.get("descripcion") or "").strip(),
                                    "cantidad_pedida": int(float(d.get("cantidad_pedida") or 0)),
                                    "cantidad_pickeada": int(float(d.get("cantidad_pickeada") or d.get("cantidad_pedida") or 0)),
                                    "lotes": str(d.get("lotes_pickeados") or d.get("lote_asignado") or "S/L").strip(),
                                })
                        except Exception:
                            pass

                    unid_tot_emp = 0
                    if lineas:
                        for idx_l, lin in enumerate(lineas, start=1):
                            sol_u = int(lin.get("cantidad_pedida") or lin.get("cantidad") or 0)
                            pick_u = int(lin.get("cantidad_pickeada") or sol_u)
                            unid_tot_emp += pick_u
                            filas_detalle_ns.append({
                                "Numero_OV_NetSuite": ov_limpia,
                                "Codigo_WMS": ov_cod,
                                "Fecha_OV": fecha_ov,
                                "Cliente": cli_nom,
                                "Comuna_Despacho": comuna_nom,
                                "Modalidad_Empaque": tipo_emp,
                                "Cantidad_Bultos_Pallets": cant_bultos,
                                "LPN_Despacho": lpn_cod,
                                "Linea_NS": lin.get("linea_ns") or idx_l,
                                "SKU": str(lin.get("sku") or "").strip().upper(),
                                "Descripcion": str(lin.get("descripcion") or "").strip(),
                                "Cantidad_Solicitada": sol_u,
                                "Cantidad_Facturar_Despachar": pick_u,
                                "Lotes_y_Vencimientos": str(lin.get("lotes") or "S/L").strip(),
                                "Estado_Facturacion": ov_item.get("estado", "PENDIENTE_FACTURACION"),
                            })
                    else:
                        unid_tot_emp = int(ov_item.get("unidades_pickeadas") or ov_item.get("unidades") or 1)
                        filas_detalle_ns.append({
                            "Numero_OV_NetSuite": ov_limpia,
                            "Codigo_WMS": ov_cod,
                            "Fecha_OV": fecha_ov,
                            "Cliente": cli_nom,
                            "Comuna_Despacho": comuna_nom,
                            "Modalidad_Empaque": tipo_emp,
                            "Cantidad_Bultos_Pallets": cant_bultos,
                            "LPN_Despacho": lpn_cod,
                            "Linea_NS": 1,
                            "SKU": "CONSOLIDADO",
                            "Descripcion": "ORDEN EMPACADA EN WMS",
                            "Cantidad_Solicitada": int(ov_item.get("unidades") or unid_tot_emp),
                            "Cantidad_Facturar_Despachar": unid_tot_emp,
                            "Lotes_y_Vencimientos": "S/L",
                            "Estado_Facturacion": ov_item.get("estado", "PENDIENTE_FACTURACION"),
                        })

                    filas_resumen_ov.append({
                        "Numero_OV_NetSuite": ov_limpia,
                        "Canal": canal_str,
                        "Fecha_OV": fecha_ov,
                        "Cliente": cli_nom,
                        "Comuna_Despacho": comuna_nom,
                        "Modalidad": tipo_emp,
                        "N_Bultos_Pallets": cant_bultos,
                        "LPN_Despacho": lpn_cod,
                        "Total_Unidades_Facturar": unid_tot_emp,
                        "Estado": ov_item.get("estado", "PENDIENTE_FACTURACION"),
                    })

                df_det = pd.DataFrame(filas_detalle_ns)
                df_res = pd.DataFrame(filas_resumen_ov)

                with pd.ExcelWriter(ruta_xlsx, engine="openpyxl") as writer:
                    df_det.to_excel(writer, sheet_name="1_Subida_NetSuite_Lineas", index=False)
                    df_res.to_excel(writer, sheet_name="2_Resumen_OVs_Bultos", index=False)

                wb = openpyxl.load_workbook(ruta_xlsx)
                fill_hdr = PatternFill(fill_type="solid", start_color="1E3A8A", end_color="1E3A8A")
                font_hdr = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                for ws in wb.worksheets:
                    ws.row_dimensions[1].height = 24
                    for cell in ws[1]:
                        cell.fill = fill_hdr
                        cell.font = font_hdr
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                    for col in ws.columns:
                        max_len = max(len(str(c.value or "")) for c in col)
                        col_letter = col[0].column_letter
                        ws.column_dimensions[col_letter].width = min(45, max(14, max_len + 4))
                wb.save(ruta_xlsx)

                descargar_archivo_web(
                    ruta_xlsx,
                    f"Excel Facturación NetSuite ({len(ovs_procesadas_excel)} OVs | {len(filas_detalle_ns)} líneas)",
                )
            except Exception as ex:
                notificar(f"Error exportando Excel de Facturación: {ex}", "#B91C1C")

        def marcar_ovs_como_facturadas(e=None, ov_unica: dict = None):
            if ov_unica:
                objetivos = [ov_unica]
            else:
                objetivos = [reg for _, (chk, reg) in checks_facturacion.items() if chk.value]

            if not objetivos:
                notificar("Seleccione al menos una OV para marcarla como FACTURADA.", "#D97706")
                return

            for it in objetivos:
                cambiar_estado_ov_db(it, "FACTURADO")

            notificar(f"{len(objetivos)} OV(s) marcadas como FACTURADAS en NetSuite.", "#047857")
            recargar_datos_supabase()
            renderizar_monitor_cortes_y_tablas()

        def exportar_ov_farmacia_excel_pdf(info_ov: dict = None):
            import textwrap
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

            objetivos = [info_ov] if info_ov else [
                r for r in registros_packing_db
                if r.get("estado") in ("PENDIENTE_PICKING", "PENDIENTE_PACKING", "PENDIENTE_FACTURACION")
            ]
            if not objetivos:
                notificar("No hay órdenes cargadas para exportar.", "#D97706")
                return

            mapa_sku_info = {}
            try:
                res_m = supabase.table("maestra_sku").select("*").limit(5000).execute()
                for m in (res_m.data or []):
                    s_k = str(m.get("sku") or "").strip().upper()
                    if not s_k:
                        continue
                    ean_v = (
                        m.get("codigo_barras")
                        or m.get("ean")
                        or m.get("ean_base")
                        or m.get("gtin")
                        or ""
                    )
                    inf_m = {
                        "descripcion": str(m.get("descripcion") or m.get("nombre") or "").strip(),
                        "ean": str(ean_v or "").strip(),
                    }
                    mapa_sku_info[s_k] = inf_m
                    s_limpio = s_k.split("-")[0].strip()
                    if s_limpio and s_limpio not in mapa_sku_info:
                        mapa_sku_info[s_limpio] = inf_m
            except Exception:
                pass

            try:
                os.makedirs("reportes_farmacia", exist_ok=True)
                ahora_dt = datetime.now()
                ts_arch = ahora_dt.strftime("%Y%m%d_%H%M%S")
                fecha_emision_str = ahora_dt.strftime("%d-%m-%Y %H:%M")

                for ov_reg in objetivos[:5]:
                    ov_raw = str(ov_reg.get("ov") or "OV").strip().upper()
                    ov_base = ov_raw.split("(")[0].strip()
                    ov_limpia = ov_base.removesuffix("-FA").strip()
                    cli_nom = str(ov_reg.get("cliente") or "CLIENTE / DESTINO").strip()
                    comuna_nom = str(ov_reg.get("comuna") or "SANTIAGO").strip()
                    tipo_emp = str(ov_reg.get("tipo_empaque") or "BULTO").strip()
                    cant_bultos = int(ov_reg.get("bultos") or 1)
                    lpn_asociado_str = str(ov_reg.get("lpn") or f"LPN-PK-{ov_limpia}").strip()

                    lineas_exportar = []
                    for ld in (ov_reg.get("lineas_detalle") or []):
                        sku_c = str(ld.get("sku") or "").strip().upper()
                        sku_limpio = sku_c.split("-")[0].strip()
                        info_m = mapa_sku_info.get(sku_c) or mapa_sku_info.get(sku_limpio) or {}
                        ean_c = str(ld.get("ean") or info_m.get("ean") or sku_c).strip()
                        desc_c = str(ld.get("descripcion") or info_m.get("descripcion") or "").strip()
                        sol_c = int(float(ld.get("cantidad_pedida") or ld.get("cantidad") or 0))
                        pick_c = int(float(ld.get("cantidad_pickeada") or sol_c))
                        lotes_c = str(ld.get("lotes") or ld.get("lotes_pickeados") or "S/L").strip()
                        lineas_exportar.append({
                            "sku": sku_c,
                            "ean": ean_c,
                            "descripcion": desc_c,
                            "solicitado": sol_c,
                            "pickeado": pick_c,
                            "lotes": lotes_c,
                        })

                    ruta_excel = os.path.join("reportes_farmacia", f"PackingList_{ov_limpia}_{ts_arch}.xlsx")
                    wb = openpyxl.Workbook()
                    ws = wb.active
                    ws.title = "Packing_List"

                    ws["A1"] = "LUDIPEK WMS"
                    ws["A1"].font = Font(name="Calibri", size=16, bold=True, color="1E3A8A")
                    ws["C1"] = f"PACKING LIST OFICIAL - OV {ov_limpia} | {tipo_emp}S: {cant_bultos} | COMUNA: {comuna_nom}"
                    ws["C1"].font = Font(name="Calibri", size=13, bold=True)
                    ws["C2"] = f"Cliente: {cli_nom}   |   LPN: {lpn_asociado_str}   |   Fecha: {fecha_emision_str}"
                    ws["C2"].font = Font(name="Calibri", size=11)

                    encabezados = [
                        "ORDEN (OV/OT)",
                        "COMUNA",
                        "EMPAQUE",
                        "BULTOS",
                        "CLIENTE / DESTINO",
                        "SKU",
                        "EAN / GTIN Base",
                        "Descripción",
                        "Solicitado",
                        "Empacado",
                        "Lotes y Vencimientos",
                    ]
                    fill_hdr = PatternFill(fill_type="solid", start_color="1E3A8A", end_color="1E3A8A")
                    font_hdr = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                    borde_fino = Side(style="thin", color="CBD5E1")
                    border_celda = Border(left=borde_fino, right=borde_fino, top=borde_fino, bottom=borde_fino)

                    for col_idx, texto_h in enumerate(encabezados, start=1):
                        c = ws.cell(row=4, column=col_idx, value=texto_h)
                        c.fill = fill_hdr
                        c.font = font_hdr
                        c.alignment = Alignment(horizontal="center", vertical="center")
                        c.border = border_celda

                    for r_idx, lin in enumerate(lineas_exportar, start=5):
                        valores_fila = [
                            ov_limpia,
                            comuna_nom,
                            tipo_emp,
                            cant_bultos,
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
                            celda.font = Font(name="Calibri", size=11)
                            celda.border = border_celda

                    wb.save(ruta_excel)
                    descargar_o_abrir_archivo(self.page, ruta_excel)
            except Exception as ex:
                notificar(f"Error al generar Packing List: {ex}", "#B91C1C")

        def renderizar_monitor_cortes_y_tablas():
            txt_t, col_t = obtener_tip_corte_actual()
            lbl_tip_corte.value = txt_t
            lbl_tip_corte.color = col_t

            # 1. Separar OVs activas en Bodega (PENDIENTE_PICKING y PENDIENTE_PACKING) vs OVs en FACTURACIÓN
            ovs_operativas_bodega = [
                r for r in registros_packing_db
                if r.get("estado") in ("PENDIENTE_PICKING", "PENDIENTE_PACKING", "EN_PICKING", "PREVISUALIZADA")
            ]
            ovs_en_facturacion = [
                r for r in registros_packing_db
                if r.get("estado") == "PENDIENTE_FACTURACION"
                or (sw_ver_ya_facturadas.value and r.get("estado") == "FACTURADO")
            ]

            mapa_ovs_unicas = {}
            for item_db in ovs_operativas_bodega:
                mapa_ovs_unicas[item_db["ov"]] = item_db
            for item_ns in olas_extraidas_ns:
                if item_ns["ov"] not in mapa_ovs_unicas:
                    mapa_ovs_unicas[item_ns["ov"]] = item_ns

            todas_ovs_activas = list(mapa_ovs_unicas.values())

            cortes_orden = ["09:00", "10:00", "12:00", "13:00", ">13:00"]
            agrupado_cortes = {c: [] for c in cortes_orden}
            for item in todas_ovs_activas:
                c_key = item.get("corte", "09:00")
                if c_key not in agrupado_cortes:
                    c_key = ">13:00"
                agrupado_cortes[c_key].append(item)

            lbl_corte_09.value = f"{len(agrupado_cortes['09:00']):02d}"
            lbl_corte_10.value = f"{len(agrupado_cortes['10:00']):02d}"
            lbl_corte_12.value = f"{len(agrupado_cortes['12:00']):02d}"
            lbl_corte_13.value = f"{len(agrupado_cortes['13:00']):02d}"

            ovs_pack_filtradas = [
                r for r in ovs_operativas_bodega
                if filtro_corte_activo == "TODOS" or r.get("corte") == filtro_corte_activo
            ]
            normales_pack = [r for r in ovs_pack_filtradas if not r.get("es_farmacia")]
            farmacias_pack = [r for r in ovs_pack_filtradas if r.get("es_farmacia")]

            pend_fact_cnt = sum(1 for r in registros_packing_db if r.get("estado") == "PENDIENTE_FACTURACION")

            lbl_kpi_total_ovs.value = str(len(ovs_pack_filtradas))
            lbl_kpi_ov_normal.value = str(len(normales_pack))
            lbl_kpi_ov_farma.value = str(len(farmacias_pack))
            lbl_kpi_pend_fact.value = str(pend_fact_cnt)

            fila_barras_cortes.controls.clear()
            col_detalle_ovs_por_corte.controls.clear()
            max_corte_cnt = max([len(v) for v in agrupado_cortes.values()] + [1])

            for c_label in cortes_orden:
                lista_c = agrupado_cortes[c_label]
                listas_pack_c = sum(1 for x in lista_c if x.get("estado") == "PENDIENTE_PACKING")
                fila_barras_cortes.controls.append(
                    construir_barra_corte(
                        c_label,
                        len(lista_c),
                        listas_pack_c,
                        max_corte_cnt,
                        lambda e, c=c_label: (cambiar_filtro_estado_interno(c), renderizar_monitor_cortes_y_tablas()),
                    )
                )

                if lista_c:
                    chips_ov = []
                    for x_ov in lista_c[:12]:
                        es_p_pack = x_ov.get("estado") == "PENDIENTE_PACKING"
                        es_fa = x_ov.get("es_farmacia")
                        chips_ov.append(
                            ft.Container(
                                padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                                bgcolor="#065F46" if es_p_pack else ("#78350F" if es_fa else "#1E3A8A"),
                                border_radius=4,
                                border=ft.Border.all(1, "#34D399" if es_p_pack else ("#FBBF24" if es_fa else "#38BDF8")),
                                tooltip=f"OV {x_ov['ov']} | {x_ov['cliente']} | {x_ov['estado']}",
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
                    chips_ov = [ft.Text("Sin OVs pendientes en este corte", size=10, color="#64748B")]

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
                                            f"{len(lista_c)} OVs Activas ({listas_pack_c} en Packing)",
                                            size=10,
                                            weight=ft.FontWeight.W_600,
                                            color="#34D399" if listas_pack_c > 0 else TEXT_MUTED,
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

            # Llenar Tabla Línea 1: OV Estándar (Solo PENDIENTE_PICKING y PENDIENTE_PACKING)
            tabla_packing_normal.rows.clear()
            for r_norm in normales_pack:
                est_n = r_norm["estado"]
                badge_n = (
                    crear_badge_estado("PENDIENTE PACKING", "#0369A1", "#E0F2FE")
                    if est_n == "PENDIENTE_PACKING"
                    else crear_badge_estado("PENDIENTE PICKING", "#92400E", "#FEF3C7")
                )
                tabla_packing_normal.rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(r_norm["ov"], weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(str(r_norm.get("fecha_ov") or "-"), size=11, color="#34D399")),
                            ft.DataCell(ft.Text(f"{r_norm['corte']} hrs", size=11, weight=ft.FontWeight.BOLD, color="#A78BFA")),
                            ft.DataCell(ft.Text(r_norm["cliente"][:32], size=11, color=TEXT_WHITE)),
                            ft.DataCell(badge_n),
                            ft.DataCell(
                                ft.Row(
                                    [
                                        boton_primario(
                                            "FIN PICKING" if est_n == "PENDIENTE_PICKING" else "EN PACKING ✓",
                                            ft.Icons.PLAY_ARROW_ROUNDED,
                                            lambda ev, it=r_norm: cambiar_estado_ov_db(it, "PENDIENTE_PACKING") or renderizar_monitor_cortes_y_tablas(),
                                            "#0284C7" if est_n == "PENDIENTE_PICKING" else "#334155",
                                            height_val=26,
                                        ),
                                        boton_primario(
                                            "EMPACAR -> FACTURACIÓN",
                                            ft.Icons.INVENTORY_2_OUTLINED,
                                            lambda ev, it=r_norm: abrir_modal_empaque_y_pasar_a_facturacion(it),
                                            "#047857",
                                            height_val=26,
                                        ),
                                        boton_primario(
                                            "VER SKUs",
                                            ft.Icons.VISIBILITY_OUTLINED,
                                            lambda ev, it=r_norm: mostrar_modal_detalle_ov(it["ov"], it),
                                            ACCENT_TEAL,
                                            height_val=26,
                                        ),
                                    ],
                                    spacing=5,
                                    tight=True,
                                )
                            ),
                        ]
                    )
                )

            # Llenar Tabla Línea 2: OV Farmacia (-FA) (Solo PENDIENTE_PICKING y PENDIENTE_PACKING)
            tabla_packing_farmacia.rows.clear()
            for r_fa in farmacias_pack:
                est_f = r_fa["estado"]
                badge_f = (
                    crear_badge_estado("PENDIENTE PACKING", "#0369A1", "#E0F2FE")
                    if est_f == "PENDIENTE_PACKING"
                    else crear_badge_estado("PENDIENTE PICKING", "#92400E", "#FEF3C7")
                )
                tabla_packing_farmacia.rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(r_fa["ov"], weight=ft.FontWeight.BOLD, size=11, color="#FBBF24")),
                            ft.DataCell(ft.Text(str(r_fa.get("fecha_ov") or "-"), size=11, color="#34D399")),
                            ft.DataCell(ft.Text(f"{r_fa['corte']} hrs", size=11, weight=ft.FontWeight.BOLD, color="#A78BFA")),
                            ft.DataCell(ft.Text(r_fa["cliente"][:32], size=11, color=TEXT_WHITE)),
                            ft.DataCell(badge_f),
                            ft.DataCell(
                                ft.Row(
                                    [
                                        boton_primario(
                                            "FIN PICKING" if est_f == "PENDIENTE_PICKING" else "EN PACKING ✓",
                                            ft.Icons.PLAY_ARROW_ROUNDED,
                                            lambda ev, it=r_fa: cambiar_estado_ov_db(it, "PENDIENTE_PACKING") or renderizar_monitor_cortes_y_tablas(),
                                            "#0284C7" if est_f == "PENDIENTE_PICKING" else "#334155",
                                            height_val=26,
                                        ),
                                        boton_primario(
                                            "EMPACAR -FA -> FACTURACIÓN",
                                            ft.Icons.VERIFIED_USER_OUTLINED,
                                            lambda ev, it=r_fa: abrir_modal_empaque_y_pasar_a_facturacion(it),
                                            "#0F766E",
                                            height_val=26,
                                        ),
                                        boton_primario(
                                            "VER SKUs",
                                            ft.Icons.VISIBILITY_OUTLINED,
                                            lambda ev, it=r_fa: mostrar_modal_detalle_ov(it["ov"], it),
                                            ACCENT_TEAL,
                                            height_val=26,
                                        ),
                                    ],
                                    spacing=5,
                                    tight=True,
                                )
                            ),
                        ]
                    )
                )

            # Llenar Tabla Módulo 4: FACTURACIÓN (OVs en PENDIENTE_FACTURACION)
            q_fact = (txt_buscar_facturacion.value or "").strip().upper()
            tabla_facturacion_ns.rows.clear()
            checks_facturacion.clear()

            filtradas_fact = []
            for r_fc in ovs_en_facturacion:
                if q_fact and not any(
                    q_fact in str(r_fc.get(k, "")).upper()
                    for k in ("ov", "cliente", "comuna", "lpn", "tipo_empaque")
                ):
                    continue
                filtradas_fact.append(r_fc)

            lbl_resumen_facturacion.value = (
                f"{len(filtradas_fact)} OV(s) en bandeja de Facturación listas para descargar Excel y subir a NetSuite."
            )

            for r_fc in filtradas_fact:
                ov_c = r_fc["ov"]
                es_fa = r_fc.get("es_farmacia", False)
                est_fc = r_fc.get("estado", "PENDIENTE_FACTURACION")
                chk_f = ft.Checkbox(value=(est_fc == "PENDIENTE_FACTURACION"), active_color=ACCENT_CYAN)
                checks_facturacion[ov_c] = (chk_f, r_fc)

                badge_est_fc = (
                    crear_badge_estado("FACTURADO", "#065F46", "#D1FAE5")
                    if est_fc == "FACTURADO"
                    else crear_badge_estado("PENDIENTE FACTURACIÓN", "#1E3A8A", "#DBEAFE")
                )

                unid_emp = int(r_fc.get("unidades_pickeadas") or r_fc.get("unidades") or 0)
                bultos_txt = f"{r_fc.get('bultos', 1)} {r_fc.get('tipo_empaque', 'BULTO')}(S)"

                tabla_facturacion_ns.rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(chk_f),
                            ft.DataCell(ft.Text(ov_c, weight=ft.FontWeight.BOLD, size=11, color="#FBBF24" if es_fa else ACCENT_CYAN)),
                            ft.DataCell(ft.Text(str(r_fc.get("fecha_ov") or "-"), size=11, color="#34D399")),
                            ft.DataCell(ft.Text("FARMACIA (-FA)" if es_fa else "ESTÁNDAR", size=10, weight=ft.FontWeight.BOLD, color="#FBBF24" if es_fa else TEXT_MUTED)),
                            ft.DataCell(ft.Text(r_fc["cliente"][:28], size=11, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(str(r_fc.get("comuna") or "SANTIAGO"), size=11, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(bultos_txt, size=11, weight=ft.FontWeight.BOLD, color="#A78BFA")),
                            ft.DataCell(ft.Text(f"{unid_emp} UN", size=11, weight=ft.FontWeight.BOLD, color="#34D399")),
                            ft.DataCell(badge_est_fc),
                            ft.DataCell(
                                ft.Row(
                                    [
                                        boton_primario(
                                            "EXCEL NS",
                                            ft.Icons.TABLE_VIEW_ROUNDED,
                                            lambda ev, it=r_fc: exportar_excel_facturacion_netsuite(solo_ov=it),
                                            ACCENT_BLUE,
                                            height_val=26,
                                        ),
                                        boton_primario(
                                            "LPN BULTOS",
                                            ft.Icons.QR_CODE_2_ROUNDED,
                                            lambda ev, it=r_fc: imprimir_etiqueta_packing_bultos_ov(it),
                                            ACCENT_TEAL,
                                            height_val=26,
                                        ),
                                        boton_primario(
                                            "FACTURADA ✓",
                                            ft.Icons.CHECK_CIRCLE_OUTLINE,
                                            lambda ev, it=r_fc: marcar_ovs_como_facturadas(ov_unica=it),
                                            "#047857" if est_fc != "FACTURADO" else "#334155",
                                            height_val=26,
                                        ),
                                    ],
                                    spacing=4,
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
        dd_filtro_corte.on_change = cambiar_filtro_corte_dropdown
        txt_buscar_facturacion.on_change = lambda e: renderizar_monitor_cortes_y_tablas()
        sw_ver_ya_facturadas.on_change = lambda e: renderizar_monitor_cortes_y_tablas()

        def cargar_monitor_packing_dual(e=None):
            recargar_datos_supabase()
            renderizar_monitor_cortes_y_tablas()

        # --- 8. EXTRACCIÓN DE OLAS DESDE NETSUITE Y LIBERACIÓN A RF ---
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
                            ft.DataCell(ft.Text(str(item.get("fecha_ov") or "-"), weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                            ft.DataCell(ft.Text(f"⏱️ {item.get('corte', '09:00')} hrs", weight=ft.FontWeight.BOLD, size=11, color="#A78BFA")),
                            ft.DataCell(badge_canal),
                            ft.DataCell(ft.Text(item["cliente"][:32], size=11, color=TEXT_WHITE)),
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

        def marcar_solo_farmacia_olas(e=None):
            for item in olas_extraidas_ns:
                item["seleccionada"] = bool(item.get("es_farmacia", False))
            renderizar_tabla_previsualizacion()

        def desmarcar_todas_olas(e=None):
            for item in olas_extraidas_ns:
                item["seleccionada"] = False
            renderizar_tabla_previsualizacion()

        def obtener_skus_farmacia_supabase() -> set:
            skus_fa = set()
            try:
                res_m = supabase.table("maestra_sku").select("*").limit(5000).execute()
                for row in (res_m.data or []):
                    sku_c = str(row.get("sku") or "").strip().upper()
                    if not sku_c:
                        continue
                    marca_c = str(row.get("marca") or row.get("categoria") or "").strip().upper()
                    ubic_fija = str(row.get("ubicacion_picking_fija") or row.get("ubicacion_picking") or "").strip().upper()
                    if "BOEHRINGER" in marca_c or "FARM" in marca_c or "-FA" in marca_c or "FARM" in ubic_fija or sku_c.endswith("-FA"):
                        skus_fa.add(sku_c)
                        skus_fa.add(sku_c.split("-")[0].strip())
            except Exception:
                pass
            return skus_fa

        def normalizar_fecha_comparacion(val_f: str) -> str:
            s = str(val_f or "").strip()
            if not s or s.upper() in ("NONE", "NULL"):
                return ""
            parte_fecha = s.replace("T", " ").split()[0].strip()
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y"):
                try:
                    return datetime.strptime(parte_fecha, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            return parte_fecha[:10]

        def extraer_ordenes_netsuite(e=None):
            nonlocal olas_extraidas_ns
            f_desde = normalizar_fecha_comparacion(txt_fecha_desde.value)
            f_hasta = normalizar_fecha_comparacion(txt_fecha_hasta.value)

            if not NETSUITE_CONECTADO:
                notificar(f"Módulo conexion_erp no conectado: {ERROR_DETALLE_ERP}", "#D97706")
                cargar_monitor_packing_dual()
                return

            txt_estado_erp.value = f"Consultando OVs en NetSuite ({f_desde} a {f_hasta})..."
            txt_estado_erp.color = ACCENT_CYAN
            cont_tabla_prev_ns.visible = True
            page.update()

            try:
                skus_fa_catalogo = obtener_skus_farmacia_supabase()
                q_ov = f"""
                    SELECT
                        t.id AS ov_internal_id,
                        t.type AS tipo_doc,
                        t.tranid AS numero_ov,
                        t.memo AS nota_ot,
                        TO_CHAR(t.trandate, 'YYYY-MM-DD') AS fecha_ov,
                        BUILTIN.DF(t.entity) AS cliente,
                        BUILTIN.DF(t.transferlocation) AS bodega_destino,
                        BUILTIN.DF(tl.location) AS bodega_ns,
                        i.itemid AS sku,
                        BUILTIN.DF(tl.item) AS descripcion,
                        ABS(tl.quantity) AS cantidad
                    FROM transaction t
                    INNER JOIN transactionline tl ON t.id = tl.transaction
                    INNER JOIN item i ON tl.item = i.id
                    WHERE t.type IN ('SalesOrd', 'TrnfrOrd')
                    AND tl.mainline = 'F'
                    AND t.trandate >= TO_DATE('{f_desde}', 'YYYY-MM-DD')
                    AND t.trandate <= TO_DATE('{f_hasta}', 'YYYY-MM-DD')
                    ORDER BY t.id DESC
                """
                df_ov = consultar_netsuite(q_ov, max_registros=1000)

                if df_ov is None or df_ov.empty:
                    notificar(f"No se encontraron OVs entre {f_desde} y {f_hasta}.", "#D97706")
                    txt_estado_erp.value = f"Sin OVs en {f_desde}..{f_hasta}."
                    txt_estado_erp.color = "#FBBF24"
                    page.update()
                    return

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
                    if not sku_str or sku_str in ("NONE", "NULL"):
                        continue

                    fh_raw = str(fila.get("fecha_ov") or "")
                    f_ov_norm = normalizar_fecha_comparacion(fh_raw)
                    desc_str = str(fila.get("descripcion") or "").strip()
                    bodega_ns = str(fila.get("bodega_ns") or "")
                    tipo_doc = str(fila.get("tipo_doc") or "").strip()
                    es_traslado = (tipo_doc == "TrnfrOrd") or ("TRASLADO" in str(fila.get("nota_ot") or "").upper())

                    if es_traslado:
                        ov_base = ov_raw.replace("OT-", "").strip()
                        ov_clave = f"OT-{ov_base}"
                        cli_str = str(fila.get("bodega_destino") or fila.get("nota_ot") or "BODEGA CONCEPCION").strip()
                        es_linea_fa = True
                    else:
                        cli_str = str(fila.get("cliente") or "CLIENTE").strip()
                        es_linea_fa = (
                            sku_str in skus_fa_catalogo
                            or sku_str.split("-")[0].strip() in skus_fa_catalogo
                            or detectar_es_farmacia_texto(ov_raw, bodega_ns)
                        )
                        ov_base = ov_raw.removesuffix("-FA").strip()
                        ov_clave = f"{ov_base}-FA" if es_linea_fa else ov_base

                    if ov_clave not in agrupado_olas:
                        agrupado_olas[ov_clave] = {
                            "ov": ov_clave,
                            "ov_original": ov_raw,
                            "fecha_ov": f_ov_norm or f_desde,
                            "cliente": cli_str,
                            "comuna": "CONCEPCIÓN" if "CONCEPCION" in cli_str.upper() else "SANTIAGO",
                            "fecha_hora": fh_raw,
                            "corte": clasificar_corte_horario(None, corte_forzado_ui),
                            "es_farmacia": es_linea_fa,
                            "unidades": 0,
                            "lineas_cnt": 0,
                            "estado": "PREVISUALIZADA",
                            "seleccionada": True,
                            "lineas_detalle": [],
                        }
                    agrupado_olas[ov_clave]["unidades"] += cant_item
                    agrupado_olas[ov_clave]["lineas_cnt"] += 1
                    agrupado_olas[ov_clave]["lineas_detalle"].append({
                        "sku": sku_str,
                        "descripcion": desc_str,
                        "cantidad": cant_item,
                        "es_farmacia": es_linea_fa,
                    })

                olas_extraidas_ns = list(agrupado_olas.values())
                cant_fa = sum(1 for x in olas_extraidas_ns if x.get("es_farmacia"))
                cant_norm = len(olas_extraidas_ns) - cant_fa
                txt_estado_erp.value = f"Extracción exitosa: {len(olas_extraidas_ns)} Olas ({cant_norm} Estándar | {cant_fa} Farmacia -FA)."
                txt_estado_erp.color = "#34D399"
                renderizar_tabla_previsualizacion()
            except Exception as ex:
                txt_estado_erp.value = f"Error consultando NetSuite: {ex}"
                txt_estado_erp.color = "#F87171"
                page.update()

        def liberar_olas_a_terminal_rf(e=None):
            seleccionadas = [
                item for item in olas_extraidas_ns
                if (checks_liberacion.get(item["ov"]) and checks_liberacion[item["ov"]].value)
                or (item["ov"] not in checks_liberacion and item.get("seleccionada", False))
            ]
            if not seleccionadas:
                notificar("Seleccione al menos una Orden de Venta para liberar a RF.", "#D97706")
                return

            corte_forzado_ui = None if dd_corte_asignar.value == "AUTO" else dd_corte_asignar.value
            liberadas_ok = 0
            ovs_liberadas_set = set()
            bodega_act = obtener_bodega_activa(self.page)

            for item in seleccionadas:
                corte_final = corte_forzado_ui or item.get("corte", "09:00")
                es_fa = bool(item.get("es_farmacia"))
                ov_final = str(item["ov"]).strip()
                if es_fa and not ov_final.upper().endswith("-FA") and not ov_final.upper().startswith("OT-"):
                    ov_final = f"{ov_final}-FA"

                cli_nom = str(item.get("cliente") or "CLIENTE REGISTRADO").strip()
                canal_str = "FARMACIA (-FA)" if es_fa else "ESTANDAR"
                id_ext_str = str(item.get("id_externo_ns") or item.get("ov_original") or ov_final).strip()

                # Estado inicial estricto: PENDIENTE_PICKING
                payload_ov = {
                    "bodega": bodega_act,
                    "id_externo_ns": id_ext_str,
                    "numero_ov": ov_final,
                    "cliente_nombre": cli_nom,
                    "canal_venta": canal_str,
                    "fecha_emision_ns": datetime.now().isoformat(),
                    "estado_ns": "PENDIENTE_PICKING",
                }

                id_ov_db = None
                try:
                    r_exist = supabase.table("netsuite_ordenes_venta").select("id").eq("numero_ov", ov_final).limit(1).execute()
                    if r_exist.data:
                        id_ov_db = r_exist.data[0].get("id")
                        supabase.table("netsuite_ordenes_venta").update(payload_ov).eq("id", id_ov_db).execute()
                    else:
                        r_ins = supabase.table("netsuite_ordenes_venta").insert(payload_ov).execute()
                        if r_ins.data:
                            id_ov_db = r_ins.data[0].get("id")
                except Exception:
                    try:
                        copia_sb = dict(payload_ov)
                        copia_sb.pop("bodega", None)
                        r_ins2 = supabase.table("netsuite_ordenes_venta").insert(copia_sb).execute()
                        if r_ins2.data:
                            id_ov_db = r_ins2.data[0].get("id")
                    except Exception:
                        pass

                lineas_det = item.get("lineas_detalle") or []
                if id_ov_db is not None and lineas_det:
                    try:
                        supabase.table("netsuite_detalle_ov").delete().eq("orden_id", id_ov_db).execute()
                    except Exception:
                        pass
                    lote_detalles = [
                        {
                            "orden_id": int(id_ov_db),
                            "linea_ns": idx_l,
                            "sku": str(lin.get("sku") or "SKU").strip().upper(),
                            "cantidad_pedida": int(float(lin.get("cantidad") or 1)),
                            "cantidad_comprometida": int(float(lin.get("cantidad") or 1)),
                            "cantidad_pickeada": 0,
                            "lote_asignado": "",
                            "estado_linea": "PENDIENTE",
                            "lotes_pickeados": "",
                        }
                        for idx_l, lin in enumerate(lineas_det, start=1)
                    ]
                    try:
                        supabase.table("netsuite_detalle_ov").insert(lote_detalles).execute()
                    except Exception:
                        pass

                ovs_liberadas_set.add(ov_final)
                liberadas_ok += 1

            olas_extraidas_ns[:] = [it for it in olas_extraidas_ns if it["ov"] not in ovs_liberadas_set]
            notificar(f"¡{liberadas_ok} OVs liberadas en estado PENDIENTE DE PICKING!", "#047857")
            renderizar_tabla_previsualizacion()
            cargar_monitor_packing_dual()

        # --- 9. COMPOSICIÓN DE PANELES RESPONSIVOS ---
        panel_relojes_izquierdo = tarjeta_dark(
            ft.Column(
                [
                    ft.Text("OVs Activas por Corte Horario (Clic para filtrar)", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Row(
                        [
                            crear_caja_digital(lbl_corte_09, "Corte 09:00", ACCENT_PURPLE, 82, lambda e: aplicar_filtro_corte_rapido("09:00")),
                            crear_caja_digital(lbl_corte_10, "Corte 10:00", ACCENT_PURPLE, 82, lambda e: aplicar_filtro_corte_rapido("10:00")),
                            crear_caja_digital(lbl_corte_12, "Corte 12:00", ACCENT_PURPLE, 82, lambda e: aplicar_filtro_corte_rapido("12:00")),
                            crear_caja_digital(lbl_corte_13, "Corte 13:00", ACCENT_PURPLE, 82, lambda e: aplicar_filtro_corte_rapido("13:00")),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_AROUND,
                        wrap=True,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=8),
                    ft.Text("Flujo Operativo: Picking -> Packing -> Facturación", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ft.Row(
                        [
                            crear_caja_digital(lbl_kpi_total_ovs, "En Bodega", ACCENT_TEAL, 82, lambda e: aplicar_filtro_corte_rapido("TODOS")),
                            crear_caja_digital(lbl_kpi_ov_normal, "OV Normal", ACCENT_BLUE, 82),
                            crear_caja_digital(lbl_kpi_ov_farma, "OV Farmacia", "#D97706", 82),
                            crear_caja_digital(lbl_kpi_pend_fact, "Por Facturar", "#10B981", 82, lambda e: self.sel_sub_olas(3)),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_AROUND,
                        wrap=True,
                    ),
                ],
                spacing=6,
            ),
        )

        panel_grafico_derecho = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Distribución de OVs Activas en Bodega por Corte Horario", size=12.5, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            ft.Row(
                                [
                                    ft.Container(width=10, height=10, bgcolor=ACCENT_BLUE, border_radius=2),
                                    ft.Text("Pendiente Picking", size=10, color=TEXT_MUTED),
                                    ft.Container(width=10, height=10, bgcolor="#FBBF24", border_radius=2),
                                    ft.Text("Farmacia (-FA)", size=10, color=TEXT_MUTED),
                                    ft.Container(width=10, height=10, bgcolor="#10B981", border_radius=2),
                                    ft.Text("En Packing", size=10, color=TEXT_MUTED),
                                ],
                                spacing=6,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=6),
                    ft.ResponsiveRow(
                        [
                            ft.Container(
                                col={"xs": 12, "sm": 12, "md": 5, "lg": 5, "xl": 4},
                                height=145,
                                padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                                bgcolor="#181E20",
                                border_radius=6,
                                alignment=ft.Alignment.BOTTOM_CENTER,
                                content=fila_barras_cortes,
                            ),
                            ft.Container(
                                col={"xs": 12, "sm": 12, "md": 7, "lg": 7, "xl": 8},
                                height=145,
                                padding=8,
                                bgcolor="#181E20",
                                border_radius=6,
                                content=col_detalle_ovs_por_corte,
                            ),
                        ],
                        spacing=8,
                        run_spacing=8,
                    ),
                ],
                spacing=6,
            ),
        )

        bloque_superior_kpi_cortes = ft.ResponsiveRow(
            [
                ft.Container(col={"xs": 12, "sm": 12, "md": 12, "lg": 5, "xl": 4}, content=panel_relojes_izquierdo),
                ft.Container(col={"xs": 12, "sm": 12, "md": 12, "lg": 7, "xl": 8}, content=panel_grafico_derecho),
            ],
            spacing=10,
            run_spacing=10,
        )

        def toggle_visibilidad_prev_ns(e=None):
            cont_tabla_prev_ns.visible = not cont_tabla_prev_ns.visible
            page.update()

        tarjeta_extraccion_netsuite = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        "PRE-VISUALIZACIÓN DE OLAS EXTRAÍDAS DESDE NETSUITE (NACEN EN PENDIENTE DE PICKING)",
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
                                    boton_primario("PLEGAR / DESPLEGAR", ft.Icons.UNFOLD_LESS_ROUNDED, toggle_visibilidad_prev_ns, "#1E3A8A", height_val=30),
                                    boton_primario("MARCAR TODAS", ft.Icons.CHECK_BOX_OUTLINED, marcar_todas_olas, "#334155", height_val=30),
                                    boton_primario("SOLO FARMACIA (-FA)", ft.Icons.MEDICAL_SERVICES_OUTLINED, marcar_solo_farmacia_olas, "#D97706", height_val=30),
                                    boton_primario("DESMARCAR TODAS", ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED, desmarcar_todas_olas, "#475569", height_val=30),
                                    boton_primario("2. LIBERAR OLAS A PICKING RF", ft.Icons.SEND_ROUNDED, liberar_olas_a_terminal_rf, "#047857", height_val=30),
                                ],
                                spacing=6,
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

        col_wrapper_pack_1 = ft.Container(
            col={"xs": 12, "sm": 12, "md": 12, "lg": 12, "xl": 12},
            content=tarjeta_dark(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, color=ACCENT_CYAN, size=18),
                                        ft.Text(
                                            "LÍNEA DE PACKING 1: ÓRDENES DE VENTA ESTÁNDAR (AL CERRAR PACKING PASAN A FACTURACIÓN)",
                                            size=12.5,
                                            weight=ft.FontWeight.BOLD,
                                            color=ACCENT_CYAN,
                                        ),
                                    ],
                                    spacing=6,
                                ),
                                boton_primario(
                                    "ALTERNAR VISTA (1 COL / 2 COL)",
                                    ft.Icons.VIEW_COLUMN_OUTLINED,
                                    lambda e: alternar_disposicion_packing(),
                                    "#334155",
                                    height_val=26,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            wrap=True,
                        ),
                        ft.Divider(color=BORDER_COLOR, height=1),
                        cont_tabla_pack_norm,
                    ],
                    spacing=8,
                ),
            ),
        )

        col_wrapper_pack_2 = ft.Container(
            col={"xs": 12, "sm": 12, "md": 12, "lg": 12, "xl": 12},
            content=tarjeta_dark(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.MEDICAL_SERVICES_OUTLINED, color="#FBBF24", size=18),
                                        ft.Text(
                                            "LÍNEA DE PACKING 2: ÓRDENES DE VENTA FARMACIA Y TRASLADOS (OV -FA / OT)",
                                            size=12.5,
                                            weight=ft.FontWeight.BOLD,
                                            color="#FBBF24",
                                        ),
                                    ],
                                    spacing=6,
                                ),
                                boton_primario(
                                    "EXPORTAR PACKING LISTS (EXCEL)",
                                    ft.Icons.TABLE_VIEW_OUTLINED,
                                    lambda e: exportar_ov_farmacia_excel_pdf(None),
                                    "#B45309",
                                    height_val=26,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            wrap=True,
                        ),
                        ft.Divider(color=BORDER_COLOR, height=1),
                        cont_tabla_pack_farm,
                    ],
                    spacing=8,
                ),
            ),
        )

        def alternar_disposicion_packing():
            modo_columnas_packing["apilado"] = not modo_columnas_packing["apilado"]
            if modo_columnas_packing["apilado"]:
                col_wrapper_pack_1.col = {"xs": 12, "sm": 12, "md": 12, "lg": 12, "xl": 12}
                col_wrapper_pack_2.col = {"xs": 12, "sm": 12, "md": 12, "lg": 12, "xl": 12}
            else:
                col_wrapper_pack_1.col = {"xs": 12, "sm": 12, "md": 12, "lg": 6, "xl": 6}
                col_wrapper_pack_2.col = {"xs": 12, "sm": 12, "md": 12, "lg": 6, "xl": 6}
            page.update()

        fila_estaciones_packing_duales = ft.ResponsiveRow(
            [col_wrapper_pack_1, col_wrapper_pack_2],
            spacing=10,
            run_spacing=10,
        )

        # SUBVISTA 4: NUEVO MÓDULO DE FACTURACIÓN (SUBIDA A NETSUITE)
        tarjeta_modulo_facturacion = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Icon(ft.Icons.RECEIPT_LONG_ROUNDED, color="#34D399", size=22),
                                            ft.Text(
                                                "4. MÓDULO DE FACTURACIÓN: ÓRDENES EMPACADAS PENDIENTES DE FACTURAR EN NETSUITE",
                                                size=14,
                                                weight=ft.FontWeight.W_900,
                                                color=TEXT_WHITE,
                                            ),
                                        ],
                                        spacing=8,
                                    ),
                                    lbl_resumen_facturacion,
                                ],
                                spacing=2,
                            ),
                            ft.Row(
                                [
                                    txt_buscar_facturacion,
                                    sw_ver_ya_facturadas,
                                    boton_primario(
                                        "DESCARGAR EXCEL PARA SUBIR A NETSUITE (FACTURACIÓN)",
                                        ft.Icons.CLOUD_UPLOAD_ROUNDED,
                                        exportar_excel_facturacion_netsuite,
                                        "#047857",
                                        height_val=34,
                                    ),
                                    boton_primario(
                                        "MARCAR SELECCIONADAS COMO FACTURADAS",
                                        ft.Icons.DONE_ALL_ROUNDED,
                                        marcar_ovs_como_facturadas,
                                        ACCENT_BLUE,
                                        height_val=34,
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
                    ft.Divider(color=BORDER_COLOR, height=4),
                    cont_tabla_facturacion,
                ],
                spacing=8,
            )
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
                fila_estaciones_packing_duales,
            ],
            spacing=10,
        )

        subvista_solo_facturacion = ft.Column(
            [
                tarjeta_modulo_facturacion,
            ],
            spacing=10,
        )

        contenedor_subvista_olas = ft.Container(content=subvista_monitor_completo)

        def toggle_kpis_superiores(e=None):
            bloque_superior_kpi_cortes.visible = not bloque_superior_kpi_cortes.visible
            page.update()

        chip_tip_horario = ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            bgcolor="#181E20",
            border_radius=6,
            border=ft.Border.all(1, "#38BDF8"),
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.ACCESS_TIME_FILLED_ROUNDED, color="#38BDF8", size=16),
                            ft.Text("FLUJO: PICKING -> PACKING -> FACTURACIÓN  |", size=11, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            lbl_tip_corte,
                        ],
                        spacing=6,
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            boton_primario("1. MONITOR COMPLETO", ft.Icons.VIEW_QUILT_OUTLINED, lambda e: self.sel_sub_olas(0), ACCENT_TEAL, height_val=26),
                            boton_primario("2. EXTRACCIÓN", ft.Icons.CLOUD_DOWNLOAD_OUTLINED, lambda e: self.sel_sub_olas(1), "#1E3A8A", height_val=26),
                            boton_primario("3. PACKING 1 Y 2", ft.Icons.INVENTORY_OUTLINED, lambda e: self.sel_sub_olas(2), "#0F766E", height_val=26),
                            boton_primario("4. FACTURACIÓN NETSUITE", ft.Icons.RECEIPT_LONG_ROUNDED, lambda e: self.sel_sub_olas(3), "#047857", height_val=26),
                            boton_primario("OCULTAR / VER KPIs", ft.Icons.VISIBILITY_OUTLINED, toggle_kpis_superiores, "#475569", height_val=26),
                        ],
                        spacing=6,
                        wrap=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                wrap=True,
            ),
        )

        barra_titulo_monitor = ft.Container(
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
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
                                        "OLAS DE PICKING, PACKING POR BULTOS/PALLET & FACTURACIÓN NETSUITE",
                                        size=14,
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
                                        tooltip="Refrescar Picking, Packing y Facturación",
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
            scroll=ft.ScrollMode.ALWAYS,
            expand=True,
        )

        self.vista = ft.Container(
            padding=ft.Padding.only(left=12, top=10, right=16, bottom=12),
            bgcolor=BG_MODULO,
            content=col_principal_picking,
            expand=True,
        )
        self.contenedor = contenedor_subvista_olas
        self.sub_completo = subvista_monitor_completo
        self.sub_extraccion = subvista_solo_extraccion
        self.sub_estaciones = subvista_solo_estaciones
        self.sub_facturacion = subvista_solo_facturacion
        self.cargar_monitor_packing_dual_func = cargar_monitor_packing_dual

    def cargar_monitor_packing_dual(self, e=None):
        self.cargar_monitor_packing_dual_func(e)

    def sel_sub_olas(self, idx: int):
        vistas = [
            self.sub_completo,
            self.sub_extraccion,
            self.sub_estaciones,
            self.sub_facturacion,
        ]
        self.contenedor.content = vistas[idx if 0 <= idx < len(vistas) else 0]
        self.cargar_monitor_packing_dual_func()
        self.page.update()