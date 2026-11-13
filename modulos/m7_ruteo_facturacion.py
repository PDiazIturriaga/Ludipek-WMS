import os
import re
import json
import shutil
import inspect
import urllib.parse
from datetime import datetime, date, timedelta
import pandas as pd
import flet as ft
from dependencias import *


# Lista oficial de los 24 SKUs de Arena de la Papeleta / Hoja de Ruta
SKUS_ARENAS_OFICIALES = [
    "ALUC07", "ALUC15", "ALDF07", "ALUV07", "ALUV15", "ALUB07", "ALUB15",
    "ALSC07", "ALSC15", "ALUE07", "ALUE15", "ALCP07", "ALCP15", "ALUS07",
    "ALUS15", "ALCR04", "ALQV07", "ALQB07", "ALQL07", "ALQU07", "ALQU15",
    "ALQU20", "ALQU02", "PGSB02",
]

CLIENTES_AGENDAMIENTO_CLAVE = [
    "CENCOSUD", "ERBI", "PRODUCTOS AL DETALLE", "MEDIVEN", "COMERCIALIZADORA RYA",
    "WALMART", "SMU", "FALABELLA", "RIPLEY",
]


class RuteoFacturacionModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables

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

        registros_rutas_db = []
        flota_vehiculos_db = []
        mapa_zonas_comunas = {}
        checks_seleccion_ov = {}

        def notificar(texto: str, color: str = "#0284C7"):
            from dependencias import notificar_global
            notificar_global(self.page, texto, color)

        def boton_accion(texto: str, icono, on_click, color_bg: str, height_val: int = 32, width_val=None):
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

        def texto_dark(
            label: str = "",
            width: int = None,
            expand=None,
            value: str = "",
            keyboard_type=None,
            on_change=None,
            hint_text: str = None,
        ):
            return ft.TextField(
                label=label,
                hint_text=hint_text,
                width=width,
                expand=expand,
                value=value,
                dense=True,
                text_size=11.5,
                color=TEXT_WHITE,
                bgcolor=BG_INPUT,
                border_color=BORDER_COLOR,
                focused_border_color=ACCENT_CYAN,
                label_style=ft.TextStyle(size=10.5, color=TEXT_MUTED),
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
                    content=ft.Text(text, color=TEXT_WHITE, size=11.5),
                    alignment=ft.Alignment.CENTER_LEFT,
                ),
            )

        def dropdown_dark(
            label: str = "",
            width: int = None,
            expand=None,
            value: str = None,
            options: list = None,
            on_change=None,
        ):
            opts = [
                opt_w(o.key, o.text) if isinstance(o, ft.DropdownOption) and not o.content else o
                for o in (options or [])
            ]
            dd = ft.Dropdown(
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
                text_style=ft.TextStyle(size=11.5, color=TEXT_WHITE),
                label_style=ft.TextStyle(size=10.5, color=TEXT_MUTED),
                content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                border_radius=6,
            )
            if on_change is not None:
                dd.on_change = on_change
                dd.on_select = on_change
            return dd

        def descargar_archivo_web(ruta_archivo: str, titulo_doc: str = "Documento Generado"):
            if not ruta_archivo or not os.path.exists(ruta_archivo):
                notificar("No se encontró el archivo generado en el servidor.", "#B91C1C")
                return
            try:
                nombre_orig = os.path.basename(ruta_archivo)
                base_nom, ext_nom = os.path.splitext(nombre_orig)
                limpio = "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in str(base_nom))
                while "__" in limpio:
                    limpio = limpio.replace("__", "_")
                nombre_seguro = f"{limpio.strip('_')[:45] or 'DOC'}{ext_nom.lower()}"

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

                async def _lanzar():
                    try:
                        r = self.page.launch_url(url_descarga, web_popup_window_name="_blank")
                        if inspect.iscoroutine(r):
                            await r
                    except Exception:
                        pass

                try:
                    self.page.run_task(_lanzar)
                except Exception:
                    pass

                def _cerrar_dlg(ev=None):
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
                            ft.Icon(ft.Icons.CLOUD_DOWNLOAD_ROUNDED, color="#34D399", size=22),
                            ft.Text(titulo_doc, size=14.5, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                        ],
                        spacing=8,
                    ),
                    content=ft.Column(
                        [
                            ft.Text(f"Archivo listo para descargar: {nombre_seguro}", size=12, color=ACCENT_CYAN, weight=ft.FontWeight.BOLD),
                            ft.Text("Haga clic en el botón verde para guardar el archivo en su computador:", size=11, color=TEXT_MUTED),
                        ],
                        spacing=6,
                        tight=True,
                    ),
                    actions=[
                        ft.TextButton("CERRAR", on_click=_cerrar_dlg),
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
            except Exception as ex:
                notificar(f"Error descargando archivo: {ex}", "#B91C1C")

        # =====================================================================
        # FUNCIONES DE CÁLCULO DE SLA (DESCONTANDO DOMINGOS) Y DETECCIÓN DE ZONA
        # =====================================================================
        def calcular_dias_habiles_sla(fecha_ini_str: str, fecha_fin_str: str) -> tuple:
            if not fecha_ini_str or not fecha_fin_str:
                return (0, "PENDIENTE", "PENDIENTE")
            try:
                f1 = datetime.strptime(str(fecha_ini_str)[:10], "%Y-%m-%d").date()
                f2 = datetime.strptime(str(fecha_fin_str)[:10], "%Y-%m-%d").date()
                if f2 < f1:
                    return (0, "Cumple", "Cumple")
                dias_hab = 0
                curr = f1
                while curr < f2:
                    curr += timedelta(days=1)
                    if curr.weekday() != 6:  # Descontar domingos (igual que DIA.LAB.INTL en el Excel de Yasneri)
                        dias_hab += 1
                c36 = "Cumple" if dias_hab <= 2 else "No Cumple"
                c72 = "Cumple" if dias_hab <= 3 else "No Cumple"
                return (dias_hab, c36, c72)
            except Exception:
                return (0, "PENDIENTE", "PENDIENTE")

        def detectar_requiere_agendamiento(nombre_cliente: str) -> bool:
            c_up = str(nombre_cliente or "").upper()
            return any(k in c_up for k in CLIENTES_AGENDAMIENTO_CLAVE)

        def resolver_zona_por_comuna(comuna_str: str) -> str:
            c_limpia = (
                str(comuna_str or "")
                .strip()
                .upper()
                .replace("Á", "A")
                .replace("É", "E")
                .replace("Í", "I")
                .replace("Ó", "O")
                .replace("Ú", "U")
            )
            if not c_limpia:
                return "Zona-RM"
            if c_limpia in mapa_zonas_comunas:
                return mapa_zonas_comunas[c_limpia]
            for k_com, z_val in mapa_zonas_comunas.items():
                if k_com in c_limpia or c_limpia in k_com:
                    return z_val
            return "REGIÓN / TRANSPORTE"

        # =====================================================================
        # KPIs DIGITALES SUPERIORES
        # =====================================================================
        lbl_kpi_total_ov = ft.Text("0", size=18, weight=ft.FontWeight.W_900, color=TEXT_WHITE, font_family="Consolas")
        lbl_kpi_facturadas = ft.Text("0", size=18, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_kpi_kilos_ruta = ft.Text("0 kg", size=16, weight=ft.FontWeight.W_900, color="#FBBF24", font_family="Consolas")
        lbl_kpi_arenas_sacos = ft.Text("0", size=18, weight=ft.FontWeight.W_900, color="#A78BFA", font_family="Consolas")
        lbl_kpi_otif_36 = ft.Text("100%", size=17, weight=ft.FontWeight.W_900, color="#34D399", font_family="Consolas")

        def caja_kpi_ruteo(txt_ctrl: ft.Text, etiqueta: str, color_b: str):
            return ft.Container(
                width=148,
                height=60,
                bgcolor=BG_DIGITAL,
                border_radius=6,
                border=ft.Border.all(1.5, color_b),
                alignment=ft.Alignment.CENTER,
                content=ft.Column(
                    [
                        txt_ctrl,
                        ft.Text(etiqueta, size=10, color=TEXT_MUTED, weight=ft.FontWeight.BOLD),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=2,
                ),
            )

        # =====================================================================
        # CONTROLES DE FILTRO GLOBALES, CALENDARIO Y EDICIÓN RÁPIDA MULTI-PC
        # =====================================================================
        hoy_iso = datetime.now().strftime("%Y-%m-%d")
        txt_filtro_fecha = texto_dark("Fecha Entrega / Factura (YYYY-MM-DD)", width=180, value="")
        dd_filtro_patente = dropdown_dark("Filtrar por Patente / Camión", width=190, value="TODAS", options=[opt_w("TODAS", "TODAS LAS PATENTES")])
        dd_filtro_status = dropdown_dark(
            "Filtrar Estado Ruta",
            width=180,
            value="TODOS",
            options=[
                opt_w("TODOS", "TODOS LOS ESTADOS"),
                opt_w("PENDIENTE RUTA", "PENDIENTE RUTA"),
                opt_w("EN RUTA", "EN RUTA"),
                opt_w("ENTREGADO", "ENTREGADO"),
                opt_w("REPROGRAMADO", "REPROGRAMADO"),
                opt_w("RECHAZADO", "RECHAZADO"),
            ],
        )
        txt_buscar_general = texto_dark("Buscar por OV, Factura, Cliente, Comuna o Ejecutivo...", width=250)

        def al_elegir_fecha_filtro(e):
            val_dt = getattr(e.control, "value", None)
            if val_dt:
                txt_filtro_fecha.value = val_dt.strftime("%Y-%m-%d") if hasattr(val_dt, "strftime") else str(val_dt)[:10]
                renderizar_tablas_ruteo()

        calendario_filtro_ruteo = ft.DatePicker(
            first_date=datetime(2024, 1, 1),
            last_date=datetime(2030, 12, 31),
            help_text="SELECCIONE FECHA DE ENTREGA O FACTURA",
            on_change=al_elegir_fecha_filtro,
        )
        try:
            self.page.overlay.append(calendario_filtro_ruteo)
        except Exception:
            pass

        def abrir_calendario_filtro(e=None):
            try:
                self.page.open(calendario_filtro_ruteo)
            except Exception:
                try:
                    self.page.show_dialog(calendario_filtro_ruteo)
                except Exception:
                    calendario_filtro_ruteo.open = True
                    self.page.update()

        # Controles para Asignación Masiva o Individual de Ruta (Sub-vista 2)
        dd_asignar_patente = dropdown_dark("1. Camión / Patente a Asignar", width=210)
        txt_asignar_chofer = texto_dark("2. Conductor", width=185)
        txt_asignar_peoneta1 = texto_dark("3. Peoneta 1", width=150)
        dd_asignar_vuelta = dropdown_dark(
            "4. Vuelta",
            width=110,
            value="AM",
            options=[opt_w("AM", "AM"), opt_w("PM", "PM")],
        )
        txt_asignar_fecha_ent = texto_dark("5. Fecha Entrega", width=140, value=hoy_iso)
        lbl_capacidad_camion = ft.Text(
            "Seleccione una Patente para ver los Kilos cargados vs. Capacidad del camión.",
            size=11.5,
            weight=ft.FontWeight.BOLD,
            color="#34D399",
        )

        # Controles para Agregar / Editar Camión en la Maestra de Flota (Sub-vista 4)
        txt_flota_patente = texto_dark("Patente (Ej: KSWY-43)", width=150)
        txt_flota_conductor = texto_dark("Conductor Titular", width=210)
        txt_flota_peoneta = texto_dark("Peoneta Default", width=170)
        dd_flota_tipo = dropdown_dark(
            "Tipo de Flota",
            width=180,
            value="Distribución Propia",
            options=[
                opt_w("Distribución Propia", "Distribución Propia"),
                opt_w("Flota Externa", "Flota Externa"),
                opt_w("Transporte Región", "Transporte Región"),
            ],
        )
        txt_flota_cap_kg = texto_dark("Capacidad (KG)", width=140, value="2800", keyboard_type=ft.KeyboardType.NUMBER)

        # =====================================================================
        # TABLAS DE LAS 4 SUB-VISTAS
        # =====================================================================
        # TABLA 1: MESA DE FACTURACIÓN Y CRUCE NETSUITE (Reemplaza Facturacion-Nuevo(1).xlsx)
        tabla_mesa_facturacion = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=36,
            data_row_max_height=42,
            column_spacing=12,
            horizontal_margin=8,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("SEL.", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("OV / CORTE", weight=ft.FontWeight.BOLD, size=10.5, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("N° FACTURA", weight=ft.FontWeight.BOLD, size=10.5, color="#FBBF24")),
                ft.DataColumn(ft.Text("CLIENTE / AGENDAMIENTO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("DIRECCIÓN / COMUNA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ZONA", weight=ft.FontWeight.BOLD, size=10, color="#A78BFA")),
                ft.DataColumn(ft.Text("MONTO NETO", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("BULTOS / PESO", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("ARENAS", weight=ft.FontWeight.BOLD, size=10, color="#FBBF24")),
                ft.DataColumn(ft.Text("EJECUTIVO / NOTA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("EDITAR", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        # TABLA 2: PLANIFICADOR DE RUTEO Y HOJA DE RUTA (Reemplaza PruebaYasneri.xlsm)
        tabla_ruteo_drivin = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=36,
            data_row_max_height=42,
            column_spacing=12,
            horizontal_margin=8,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("SEL.", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("PATENTE / VUELTA", weight=ft.FontWeight.BOLD, size=10.5, color="#FBBF24")),
                ft.DataColumn(ft.Text("CHOFER", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("OV / FACTURA", weight=ft.FontWeight.BOLD, size=10.5, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("CLIENTE", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("DIRECCIÓN / COMUNA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("BULTOS / GRUPO", weight=ft.FontWeight.BOLD, size=10, color="#A78BFA")),
                ft.DataColumn(ft.Text("KILOS", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("DETALLE ARENAS", weight=ft.FontWeight.BOLD, size=10, color="#FBBF24")),
                ft.DataColumn(ft.Text("NOTA DESPACHO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
            ],
            rows=[],
        )

        # TABLA 3: REPORTE DIARIO DE ENTREGAS, INCIDENCIAS Y SLA/OTIF (Reemplaza Base Reporte Diario - Yasneri.xlsx)
        tabla_entregas_sla = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=36,
            data_row_max_height=42,
            column_spacing=12,
            horizontal_margin=8,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("FECHA ENTREGA", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("PATENTE / FLOTA", weight=ft.FontWeight.BOLD, size=10, color="#FBBF24")),
                ft.DataColumn(ft.Text("OV / FACT", weight=ft.FontWeight.BOLD, size=10.5, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("CLIENTE / COMUNA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("STATUS ENTREGA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("RECIBIDO POR", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("INCIDENCIA", weight=ft.FontWeight.BOLD, size=10, color="#F87171")),
                ft.DataColumn(ft.Text("SLA 36H / 72H", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("ACCIÓN RÁPIDA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        # TABLA 4: MAESTRA DE FLOTA Y CONDUCTORES
        tabla_maestra_flota = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=34,
            data_row_max_height=40,
            column_spacing=16,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("PATENTE", weight=ft.FontWeight.BOLD, size=11, color="#FBBF24")),
                ft.DataColumn(ft.Text("CONDUCTOR TITULAR", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("PEONETA DEFAULT", weight=ft.FontWeight.BOLD, size=11, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("TIPO DE FLOTA", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("CAPACIDAD (KG)", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                ft.DataColumn(ft.Text("CAPACIDAD (TON)", weight=ft.FontWeight.BOLD, size=11, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("BODEGA", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIÓN", weight=ft.FontWeight.BOLD, size=11, color=TEXT_WHITE)),
            ],
            rows=[],
        )

        cont_t1 = envolver_tabla_scroll(tabla_mesa_facturacion, 390)
        cont_t2 = envolver_tabla_scroll(tabla_ruteo_drivin, 360)
        cont_t3 = envolver_tabla_scroll(tabla_entregas_sla, 390)
        cont_t4 = envolver_tabla_scroll(tabla_maestra_flota, 320)

        # =====================================================================
        # CARGA Y SINCRONIZACIÓN DE DATOS DESDE SUPABASE Y PACKING RF
        # =====================================================================
        def eliminar_camion_flota(patente_del: str):
            try:
                supabase.table("wms_flota_vehiculos").delete().eq("patente", patente_del).execute()
                notificar(f"Camión {patente_del} eliminado de la flota.", "#D97706")
                cargar_maestras_flota_y_zonas()
                self.page.update()
            except Exception as ex:
                notificar(f"Error eliminando camión: {ex}", "#B91C1C")

        def guardar_camion_flota(e=None):
            pat_n = (txt_flota_patente.value or "").strip().upper()
            chof_n = (txt_flota_conductor.value or "").strip().upper()
            peo_n = (txt_flota_peoneta.value or "").strip().upper()
            tipo_n = dd_flota_tipo.value or "Distribución Propia"
            try:
                cap_n = float((txt_flota_cap_kg.value or "2800").strip() or 2800)
            except Exception:
                cap_n = 2800.0

            if not pat_n or not chof_n:
                notificar("Ingrese al menos la Patente y el Conductor titular.", "#D97706")
                return

            try:
                payload_f = {
                    "patente": pat_n,
                    "conductor": chof_n,
                    "peoneta_default": peo_n,
                    "tipo_flota": tipo_n,
                    "capacidad_kg": cap_n,
                    "bodega": obtener_bodega_activa(self.page),
                }
                supabase.table("wms_flota_vehiculos").upsert(payload_f, on_conflict="patente").execute()
                txt_flota_patente.value = ""
                txt_flota_conductor.value = ""
                txt_flota_peoneta.value = ""
                notificar(f"Camión {pat_n} ({chof_n}) guardado en la Maestra de Flota.", "#047857")
                cargar_maestras_flota_y_zonas()
                self.page.update()
            except Exception as ex:
                notificar(f"Error guardando camión: {ex}", "#B91C1C")

        def cargar_maestras_flota_y_zonas():
            nonlocal flota_vehiculos_db, mapa_zonas_comunas
            try:
                res_f = supabase.table("wms_flota_vehiculos").select("*").order("patente").execute()
                flota_vehiculos_db = res_f.data or []
            except Exception:
                flota_vehiculos_db = []

            try:
                res_z = supabase.table("wms_zonas_comunas").select("*").execute()
                mapa_zonas_comunas = {
                    str(z.get("comuna") or "").strip().upper(): str(z.get("zona") or "Zona-RM").strip()
                    for z in (res_z.data or [])
                    if z.get("comuna")
                }
            except Exception:
                mapa_zonas_comunas = {}

            opts_f = [opt_w("TODAS", "TODAS LAS PATENTES"), opt_w("SIN ASIGNAR", "SIN ASIGNAR")]
            opts_asig = []
            filas_flota = []
            for v in flota_vehiculos_db:
                pat = str(v.get("patente") or "").strip().upper()
                chofer = str(v.get("conductor") or "").strip()
                peo = str(v.get("peoneta_default") or "-").strip()
                cap_k = int(float(v.get("capacidad_kg") or 2800))
                t_flota = str(v.get("tipo_flota") or "Distribución Propia")
                opts_f.append(opt_w(pat, f"{pat} ({chofer[:16]} | {cap_k}kg)"))
                opts_asig.append(opt_w(pat, f"{pat} - {chofer} ({cap_k} kg)"))
                filas_flota.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(pat, weight=ft.FontWeight.W_900, size=11.5, color="#FBBF24")),
                            ft.DataCell(ft.Text(chofer, size=11, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(peo, size=11, color=TEXT_MUTED)),
                            ft.DataCell(ft.Text(t_flota, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(f"{cap_k} kg", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                            ft.DataCell(ft.Text(f"{cap_k / 1000.0:.1f} Ton", size=11, color=TEXT_MUTED)),
                            ft.DataCell(ft.Text(str(v.get("bodega") or "Bodega Santiago"), size=11, color=TEXT_WHITE)),
                            ft.DataCell(
                                ft.Row(
                                    [
                                        boton_accion(
                                            "CARGAR",
                                            ft.Icons.EDIT_OUTLINED,
                                            lambda ev, item_v=v: (
                                                setattr(txt_flota_patente, "value", str(item_v.get("patente") or "")),
                                                setattr(txt_flota_conductor, "value", str(item_v.get("conductor") or "")),
                                                setattr(txt_flota_peoneta, "value", str(item_v.get("peoneta_default") or "")),
                                                setattr(txt_flota_cap_kg, "value", str(int(float(item_v.get("capacidad_kg") or 2800)))),
                                                self.page.update(),
                                            ),
                                            ACCENT_BLUE,
                                            height_val=26,
                                        ),
                                        boton_accion(
                                            "BORRAR",
                                            ft.Icons.DELETE_OUTLINE,
                                            lambda ev, p_del=pat: eliminar_camion_flota(p_del),
                                            "#B91C1C",
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
            dd_filtro_patente.options = opts_f
            dd_asignar_patente.options = opts_asig
            tabla_maestra_flota.rows = filas_flota

        def al_seleccionar_patente_asignar(e=None):
            pat_sel = str(dd_asignar_patente.value or "").split(" - ")[0].strip().upper()
            veh = next((x for x in flota_vehiculos_db if str(x.get("patente")).upper() == pat_sel), None)
            if veh:
                txt_asignar_chofer.value = str(veh.get("conductor") or "")
                txt_asignar_peoneta1.value = str(veh.get("peoneta_default") or "")
                cap_max = float(veh.get("capacidad_kg") or 2800)
                kilos_actuales = sum(
                    float(r.get("peso_kg") or 0)
                    for r in registros_rutas_db
                    if str(r.get("patente") or "").upper() == pat_sel
                )
                pct = int((kilos_actuales / max(1.0, cap_max)) * 100)
                lbl_capacidad_camion.value = (
                    f"Camión {pat_sel} ({veh.get('conductor')}): Cargado {kilos_actuales:.1f} kg de {cap_max:.0f} kg ({pct}%)"
                )
                lbl_capacidad_camion.color = "#F87171" if kilos_actuales > cap_max else "#34D399"
                self.page.update()

        dd_asignar_patente.on_change = al_seleccionar_patente_asignar
        dd_asignar_patente.on_select = al_seleccionar_patente_asignar

        def sincronizar_ovs_desde_packing_y_netsuite(e=None):
            """Cruza automáticamente las OVs de netsuite_ordenes_venta + netsuite_detalle_ov + maestra_sku (pesos y arenas) hacia wms_despacho_rutas."""
            bodega_act = obtener_bodega_activa(self.page)
            cargar_maestras_flota_y_zonas()

            try:
                # 1. Leer pesos desde maestra_sku
                mapa_peso_sku = {}
                res_m = supabase.table("maestra_sku").select("sku, peso_kg, descripcion").limit(5000).execute()
                for m in (res_m.data or []):
                    s_k = str(m.get("sku") or "").strip().upper()
                    if s_k:
                        p_kg = float(m.get("peso_kg") or 0.0)
                        if p_kg <= 0 and s_k.startswith("AL"):
                            if "20" in s_k:
                                p_kg = 20.0
                            elif "15" in s_k:
                                p_kg = 15.0
                            elif "07" in s_k:
                                p_kg = 7.0
                            elif "04" in s_k:
                                p_kg = 4.0
                        mapa_peso_sku[s_k] = p_kg
                        mapa_peso_sku[s_k.split("-")[0].strip()] = p_kg

                # 2. Leer OVs de netsuite_ordenes_venta y sus líneas de netsuite_detalle_ov
                res_ovs = supabase.table("netsuite_ordenes_venta").select("*").order("id", desc=True).limit(350).execute()
                ovs_lista = [r for r in (res_ovs.data or []) if coincide_bodega(r, bodega_act)]

                res_det = supabase.table("netsuite_detalle_ov").select("*").limit(3000).execute()
                det_por_id = {}
                for d in (res_det.data or []):
                    oid = d.get("orden_id")
                    if oid is not None:
                        det_por_id.setdefault(oid, []).append(d)

                # 3. Leer metadatos de bultos y comunas guardados en Packing
                meta_packing_local = {}
                if os.path.exists("config_despacho_packing.json"):
                    try:
                        with open("config_despacho_packing.json", "r", encoding="utf-8") as f_mp:
                            meta_packing_local = json.load(f_mp)
                    except Exception:
                        pass

                res_existentes = supabase.table("wms_despacho_rutas").select("numero_ov").execute()
                ovs_ya_en_rutas = {str(x.get("numero_ov") or "").strip().upper() for x in (res_existentes.data or [])}

                nuevos_registros = []
                for ov_row in ovs_lista:
                    ov_num = str(ov_row.get("numero_ov") or "").strip().upper()
                    ov_limpia = ov_num.removesuffix("-FA").strip()
                    if not ov_limpia or ov_limpia in ovs_ya_en_rutas or ov_num in ovs_ya_en_rutas:
                        continue

                    lineas = det_por_id.get(ov_row.get("id"), [])
                    peso_total_ov = 0.0
                    arenas_map = {}
                    total_sacos_arena = 0

                    for lin in lineas:
                        sku_l = str(lin.get("sku") or "").strip().upper().split("-")[0].strip()
                        cant_l = int(float(lin.get("cantidad_pickeada") or lin.get("cantidad_pedida") or 0))
                        if cant_l <= 0:
                            continue
                        peso_u = mapa_peso_sku.get(sku_l, 0.5)
                        peso_total_ov += cant_l * peso_u

                        if sku_l in SKUS_ARENAS_OFICIALES or sku_l.startswith("AL"):
                            arenas_map[sku_l] = arenas_map.get(sku_l, 0) + cant_l
                            total_sacos_arena += cant_l

                    cli_str = str(ov_row.get("cliente_nombre") or "CLIENTE").strip()
                    meta_pk = meta_packing_local.get(ov_num) or meta_packing_local.get(ov_limpia) or {}
                    comuna_str = str(meta_pk.get("comuna") or ("CONCEPCIÓN" if "CONCEPCION" in cli_str.upper() else "SANTIAGO")).strip().upper()
                    tipo_emp = str(meta_pk.get("tipo_empaque") or "BULTOS").strip().upper()
                    cant_b = int(meta_pk.get("bultos") or 1)
                    pref_b = "P" if "PALLET" in tipo_emp else "B"
                    fecha_crea = str(ov_row.get("fecha_emision_ns") or datetime.now().strftime("%Y-%m-%d"))[:10]

                    nuevos_registros.append({
                        "bodega": bodega_act,
                        "numero_ov": ov_limpia,
                        "numero_factura": "",
                        "estado_validado_ns": str(ov_row.get("estado_ns") or "Pending Fulfillment"),
                        "ola_picking": "Corte 09:00",
                        "fecha_creacion_ov": fecha_crea,
                        "fecha_aprobacion_ov": fecha_crea,
                        "fecha_picking": fecha_crea,
                        "fecha_factura": fecha_crea,
                        "fecha_entrega": hoy_iso,
                        "cliente": cli_str,
                        "requiere_agendamiento": detectar_requiere_agendamiento(cli_str),
                        "direccion": str(ov_row.get("direccion") or ""),
                        "comuna": comuna_str,
                        "zona": resolver_zona_por_comuna(comuna_str),
                        "ejecutivo_ventas": str(ov_row.get("ejecutivo") or ""),
                        "monto_neto": float(ov_row.get("monto_neto") or 0),
                        "peso_kg": round(peso_total_ov, 2),
                        "tipo_empaque": tipo_emp,
                        "cantidad_bultos": cant_b,
                        "etiqueta_bultos": f"{pref_b} {cant_b}",
                        "incluye_arenas": total_sacos_arena > 0,
                        "total_sacos_arena": total_sacos_arena,
                        "detalle_arenas": arenas_map,
                        "patente": "SIN ASIGNAR",
                        "status_entrega": "PENDIENTE RUTA",
                        "usuario_modificacion": str(getattr(self.page, "usuario_actual", "WMS")),
                    })

                if nuevos_registros:
                    supabase.table("wms_despacho_rutas").insert(nuevos_registros).execute()
                    notificar(f"Se sincronizaron {len(nuevos_registros)} nuevas OVs con cálculo automático de Kilos y Arenas.", "#047857")
                else:
                    notificar("Tabla de Facturación y Ruteo al día.", ACCENT_TEAL)

                cargar_datos_ruteo_y_facturacion()
            except Exception as ex:
                notificar(f"Aviso al sincronizar OVs: {ex}", "#D97706")
                cargar_datos_ruteo_y_facturacion()

        # =====================================================================
        # IMPORTADOR INTELIGENTE DE EXCEL "BASE" NETSUITE (Facturacion-Nuevo)
        # =====================================================================
        async def procesar_excel_base_netsuite(ruta_excel: str):
            try:
                xls = pd.ExcelFile(ruta_excel)
                hoja_usar = next((s for s in xls.sheet_names if s.lower() in ("base", "netsuit", "facturación", "entregas")), xls.sheet_names[0])
                df_raw = pd.read_excel(ruta_excel, sheet_name=hoja_usar)

                for idx_r, row_vals in df_raw.head(10).iterrows():
                    textos_fila = [str(v or "").strip() for v in row_vals.values]
                    if any("Número de documento" in t or "OV" == t.upper() for t in textos_fila):
                        df_raw.columns = textos_fila
                        df_raw = df_raw.iloc[idx_r + 1:].reset_index(drop=True)
                        break

                bodega_act = obtener_bodega_activa(self.page)
                lote_upsert = []

                for _, fila in df_raw.iterrows():
                    ov_val = str(
                        fila.get("Número de documento")
                        or fila.get("ov")
                        or fila.get("OV")
                        or ""
                    ).strip().split(".")[0].strip()
                    if not ov_val or not ov_val[0].isdigit():
                        continue

                    cli_val = str(
                        fila.get("Cliente/Trabajo: Nombre (agrupado)")
                        or fila.get("Razon Social")
                        or fila.get("CLIENTE")
                        or fila.get("Cliente")
                        or "CLIENTE"
                    ).strip()
                    dir_val = str(
                        fila.get("Dirección: Línea 1 de la dirección de envío")
                        or fila.get("DIRECCION")
                        or fila.get("Dirección")
                        or ""
                    ).strip()
                    com_val = str(
                        fila.get("Dirección: Línea 2 de la dirección de envío")
                        or fila.get("COMUNA")
                        or fila.get("Comuna")
                        or "SANTIAGO"
                    ).strip().upper()
                    ejec_val = str(
                        fila.get("Representante de ventas principal: Nombre (agrupado)")
                        or fila.get("Representante de ventas principal: ID")
                        or fila.get("EJECUTIVO VTA.")
                        or ""
                    ).strip()
                    nota_val = str(fila.get("Nota") or fila.get("NOTA") or "").strip()
                    if nota_val.upper() in ("NAN", "NONE", "0"):
                        nota_val = ""
                    vent_val = str(fila.get("Cliente/proyecto: Código postal de la dirección de envío") or "").strip()
                    if vent_val.upper() in ("NAN", "NONE"):
                        vent_val = ""

                    try:
                        monto_val = float(fila.get("Sumar importe") or fila.get("Monto") or fila.get("Monto Neto") or fila.get("Importe (neto)") or 0)
                    except Exception:
                        monto_val = 0.0

                    fact_val = str(fila.get("FACT") or fila.get("FACTURA") or "").strip().split(".")[0]
                    if fact_val.upper() in ("NAN", "NONE", "0"):
                        fact_val = ""

                    f_crea = str(fila.get("Fecha de creación") or fila.get("Fecha") or hoy_iso)[:10]
                    f_aprob = str(fila.get("LDP Fecha de aprobación") or fila.get("FECHA APROBACION") or f_crea)

                    m_ov_grupo = re.search(r"(?:OV|VA CON)\s*(\d{5,7})", nota_val.upper())
                    ov_grupo_str = m_ov_grupo.group(1) if m_ov_grupo else ""

                    lote_upsert.append({
                        "bodega": bodega_act,
                        "numero_ov": ov_val,
                        "numero_factura": fact_val,
                        "estado_validado_ns": str(fila.get("Estado validado") or "Pending Fulfillment"),
                        "fecha_creacion_ov": f_crea,
                        "fecha_aprobacion_ov": f_aprob,
                        "cliente": cli_val,
                        "requiere_agendamiento": detectar_requiere_agendamiento(cli_val),
                        "direccion": dir_val,
                        "comuna": com_val,
                        "zona": resolver_zona_por_comuna(com_val),
                        "ejecutivo_ventas": ejec_val,
                        "ventana_horaria": vent_val,
                        "monto_neto": monto_val,
                        "nota_despacho": nota_val,
                        "ov_grupo_principal": ov_grupo_str,
                        "usuario_modificacion": str(getattr(self.page, "usuario_actual", "WMS")),
                    })

                if lote_upsert:
                    mapa_unico = {}
                    for item in lote_upsert:
                        k = item["numero_ov"]
                        if k not in mapa_unico:
                            mapa_unico[k] = item
                        else:
                            mapa_unico[k]["monto_neto"] += item["monto_neto"]

                    supabase.table("wms_despacho_rutas").upsert(list(mapa_unico.values()), on_conflict="numero_ov").execute()
                    notificar(f"¡{len(mapa_unico)} OVs importadas y cruzadas desde el Excel a Supabase!", "#047857")
                    cargar_datos_ruteo_y_facturacion()
                else:
                    notificar("No se encontraron filas de OVs válidas en el Excel seleccionado.", "#D97706")
            except Exception as ex:
                notificar(f"Error importando Excel Base: {ex}", "#B91C1C")

        def al_subir_excel_picker(e):
            try:
                os.makedirs(os.path.join("assets", "uploads"), exist_ok=True)
                nombre_f = getattr(e, "file_name", None)
                if nombre_f:
                    ruta_f = os.path.join("assets", "uploads", nombre_f)
                    if os.path.exists(ruta_f):
                        self.page.run_task(procesar_excel_base_netsuite, ruta_f)
            except Exception as ex_up:
                notificar(f"Error procesando archivo subido: {ex_up}", "#B91C1C")

        def al_elegir_excel_picker(e):
            if not getattr(e, "files", None):
                return
            f_obj = e.files[0]
            if getattr(f_obj, "path", None) and os.path.exists(f_obj.path):
                self.page.run_task(procesar_excel_base_netsuite, f_obj.path)
            else:
                try:
                    url_up = self.page.get_upload_url(f_obj.name, 600)
                    picker_excel_ns.upload([ft.FilePickerUploadFile(f_obj.name, upload_url=url_up)])
                except Exception as ex_u:
                    notificar(f"No se pudo cargar el archivo en web: {ex_u}", "#B91C1C")

        picker_excel_ns = ft.FilePicker(on_result=al_elegir_excel_picker, on_upload=al_subir_excel_picker)
        try:
            self.page.overlay.append(picker_excel_ns)
        except Exception:
            pass

        # =====================================================================
        # MODAL DE EDICIÓN HUMANA AMIGABLE POR OV (FACTURA, BULTOS, ARENAS, RUTA)
        # =====================================================================
        def abrir_modal_editar_ov_completa(reg: dict):
            ov_cod = str(reg.get("numero_ov") or "")
            t_fact = texto_dark("N° Factura NetSuite", width=155, value=str(reg.get("numero_factura") or ""))
            t_ffact = texto_dark("Fecha Factura (YYYY-MM-DD)", width=165, value=str(reg.get("fecha_factura") or hoy_iso))
            t_dir = texto_dark("Dirección de Entrega", width=310, value=str(reg.get("direccion") or ""))
            t_com = texto_dark("Comuna", width=160, value=str(reg.get("comuna") or ""))
            t_zona = texto_dark("Zona", width=140, value=str(reg.get("zona") or ""))
            t_peso = texto_dark("Peso Total (KG)", width=130, value=str(reg.get("peso_kg") or 0), keyboard_type=ft.KeyboardType.NUMBER)
            t_bultos = texto_dark("Cant. Bultos/Pallets", width=140, value=str(reg.get("cantidad_bultos") or 1), keyboard_type=ft.KeyboardType.NUMBER)
            t_etiq_b = texto_dark("Etiqueta Bulto (Ej: B 1, P 1, va con...)", width=220, value=str(reg.get("etiqueta_bultos") or "B 1"))
            t_nota = texto_dark("Nota / Ventana Horaria / Transporte", width=360, value=str(reg.get("nota_despacho") or ""))
            t_recibido = texto_dark("Recibido Por (Firma Cliente)", width=220, value=str(reg.get("recibido_por") or ""))
            dd_inc = dropdown_dark(
                "Incidencia",
                width=200,
                value=str(reg.get("incidencia") or "0"),
                options=[
                    opt_w("0", "0 (Sin Incidencia)"),
                    opt_w("Packing", "Error Packing"),
                    opt_w("Facturación", "Error Facturación"),
                    opt_w("Sin Moradores", "Sin Moradores"),
                    opt_w("Rechazo Cliente", "Rechazo Cliente"),
                    opt_w("Transporte", "Atraso Transporte"),
                ],
            )

            arenas_actuales = reg.get("detalle_arenas") or {}
            if isinstance(arenas_actuales, str):
                try:
                    arenas_actuales = json.loads(arenas_actuales)
                except Exception:
                    arenas_actuales = {}

            controles_arenas = {}
            wrap_arenas = ft.Row(spacing=6, run_spacing=6, wrap=True)
            for sku_ar in SKUS_ARENAS_OFICIALES:
                val_ar = arenas_actuales.get(sku_ar, 0)
                tf_ar = texto_dark(sku_ar, width=82, value=str(val_ar) if val_ar else "0", keyboard_type=ft.KeyboardType.NUMBER)
                controles_arenas[sku_ar] = tf_ar
                wrap_arenas.controls.append(tf_ar)

            def guardar_edicion_modal(ev=None):
                try:
                    nuevas_arenas = {}
                    tot_ar = 0
                    for s_a, ctrl_a in controles_arenas.items():
                        v_int = int(float((ctrl_a.value or "0").strip() or 0))
                        if v_int > 0:
                            nuevas_arenas[s_a] = v_int
                            tot_ar += v_int

                    f_aprob_base = str(reg.get("fecha_aprobacion_ov") or reg.get("fecha_creacion_ov") or hoy_iso)[:10]
                    f_ent_base = str(reg.get("fecha_entrega") or hoy_iso)[:10]
                    dias_s, c36, c72 = calcular_dias_habiles_sla(f_aprob_base, f_ent_base)

                    payload_upd = {
                        "numero_factura": (t_fact.value or "").strip(),
                        "fecha_factura": (t_ffact.value or "").strip(),
                        "direccion": (t_dir.value or "").strip().upper(),
                        "comuna": (t_com.value or "").strip().upper(),
                        "zona": (t_zona.value or resolver_zona_por_comuna(t_com.value)).strip(),
                        "peso_kg": float((t_peso.value or "0").strip() or 0),
                        "cantidad_bultos": max(1, int(float((t_bultos.value or "1").strip() or 1))),
                        "etiqueta_bultos": (t_etiq_b.value or "B 1").strip(),
                        "nota_despacho": (t_nota.value or "").strip(),
                        "recibido_por": (t_recibido.value or "").strip().upper(),
                        "incidencia": dd_inc.value or "0",
                        "incluye_arenas": tot_ar > 0,
                        "total_sacos_arena": tot_ar,
                        "detalle_arenas": nuevas_arenas,
                        "dias_sla": dias_s,
                        "cumple_sla_36": c36,
                        "cumple_sla_72": c72,
                        "usuario_modificacion": str(getattr(self.page, "usuario_actual", "WMS")),
                        "updated_at": datetime.now().isoformat(),
                    }
                    supabase.table("wms_despacho_rutas").update(payload_upd).eq("id", reg["id"]).execute()
                    self.page.pop_dialog()
                    notificar(f"OV {ov_cod} actualizada en Supabase.", "#047857")
                    cargar_datos_ruteo_y_facturacion()
                except Exception as ex_u:
                    notificar(f"Error guardando OV {ov_cod}: {ex_u}", "#B91C1C")

            dlg_ed = ft.AlertDialog(
                modal=True,
                bgcolor="#1E293B",
                title=ft.Row(
                    [
                        ft.Icon(ft.Icons.EDIT_NOTE_ROUNDED, color=ACCENT_CYAN, size=22),
                        ft.Text(f"Ficha de Facturación, Bultos, Arenas y Ruta - OV {ov_cod}", size=14.5, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                    ],
                    spacing=8,
                ),
                content=ft.Container(
                    width=760,
                    height=430,
                    content=ft.Column(
                        [
                            ft.Text(f"CLIENTE: {reg.get('cliente', '')}", size=12, weight=ft.FontWeight.BOLD, color="#34D399"),
                            ft.Row([t_fact, t_ffact, t_peso, t_bultos, t_etiq_b], spacing=8, wrap=True),
                            ft.Row([t_dir, t_com, t_zona], spacing=8, wrap=True),
                            ft.Row([t_nota, t_recibido, dd_inc], spacing=8, wrap=True),
                            ft.Divider(color=BORDER_COLOR, height=8),
                            ft.Text("CANTIDAD DE SACOS POR SKU DE ARENA (PARA PAPELETA DE ARENAS Y HOJA DE RUTA):", size=11, weight=ft.FontWeight.BOLD, color="#FBBF24"),
                            wrap_arenas,
                        ],
                        spacing=8,
                        scroll=ft.ScrollMode.ALWAYS,
                    ),
                ),
                actions=[
                    ft.TextButton("CANCELAR", on_click=lambda ev: (self.page.pop_dialog(), self.page.update())),
                    boton_accion("GUARDAR CAMBIOS EN SUPABASE", ft.Icons.SAVE_ROUNDED, guardar_edicion_modal, "#047857", height_val=34),
                ],
            )
            self.page.show_dialog(dlg_ed)
            self.page.update()

        # =====================================================================
        # ASIGNACIÓN MASIVA DE RUTA (PATENTE, CHOFER, PEONETA, VUELTA, FECHA)
        # =====================================================================
        def asignar_camion_a_ovs_seleccionadas(e=None):
            pat_raw = str(dd_asignar_patente.value or "").split(" - ")[0].strip().upper()
            if not pat_raw:
                notificar("Seleccione primero una Patente / Camión.", "#D97706")
                return

            ids_sel = [reg["id"] for _, (chk, reg) in checks_seleccion_ov.items() if chk.value and reg.get("id")]
            if not ids_sel:
                notificar("Marque al menos una OV en la casilla izquierda para asignarle ruta.", "#D97706")
                return

            veh = next((x for x in flota_vehiculos_db if str(x.get("patente")).upper() == pat_raw), {})
            chofer_s = (txt_asignar_chofer.value or veh.get("conductor") or "").strip().upper()
            peoneta_s = (txt_asignar_peoneta1.value or "").strip().upper()
            vuelta_s = dd_asignar_vuelta.value or "AM"
            fecha_e = (txt_asignar_fecha_ent.value or hoy_iso).strip()[:10]
            t_flota = str(veh.get("tipo_flota") or ("Flota Externa" if pat_raw.startswith("EXT") else "Distribución Propia"))

            try:
                for id_r in ids_sel:
                    supabase.table("wms_despacho_rutas").update({
                        "patente": pat_raw,
                        "tipo_flota": t_flota,
                        "conductor": chofer_s,
                        "peoneta_1": peoneta_s,
                        "vuelta": vuelta_s,
                        "fecha_entrega": fecha_e,
                        "status_entrega": "EN RUTA",
                        "usuario_modificacion": str(getattr(self.page, "usuario_actual", "WMS")),
                    }).eq("id", id_r).execute()

                notificar(f"¡{len(ids_sel)} OV(s) asignadas al camión {pat_raw} ({chofer_s} - Vuelta {vuelta_s})!", "#047857")
                cargar_datos_ruteo_y_facturacion()
                al_seleccionar_patente_asignar()
            except Exception as ex:
                notificar(f"Error asignando camión: {ex}", "#B91C1C")

        def cambiar_estado_entrega_rapido(reg: dict, nuevo_status: str):
            try:
                f_aprob = str(reg.get("fecha_aprobacion_ov") or reg.get("fecha_creacion_ov") or hoy_iso)[:10]
                f_ent = str(reg.get("fecha_entrega") or hoy_iso)[:10]
                dias_s, c36, c72 = calcular_dias_habiles_sla(f_aprob, f_ent)
                supabase.table("wms_despacho_rutas").update({
                    "status_entrega": nuevo_status,
                    "dias_sla": dias_s,
                    "cumple_sla_36": c36,
                    "cumple_sla_72": c72,
                    "usuario_modificacion": str(getattr(self.page, "usuario_actual", "WMS")),
                }).eq("id", reg["id"]).execute()
                cargar_datos_ruteo_y_facturacion()
            except Exception as ex:
                notificar(f"Error actualizando estado: {ex}", "#B91C1C")

        # =====================================================================
        # EXPORTADORES OFICIALES (DRIVIN, HOJA DE RUTA + ARENAS PDF/XLSX, SLA DIARIO)
        # =====================================================================
        def obtener_registros_filtrados() -> list:
            f_fecha = (txt_filtro_fecha.value or "").strip()[:10]
            f_pat = str(dd_filtro_patente.value or "TODAS").split(" (")[0].strip().upper()
            f_st = str(dd_filtro_status.value or "TODOS").strip().upper()
            q_txt = (txt_buscar_general.value or "").strip().upper()

            filtrados = []
            for r in registros_rutas_db:
                if f_fecha:
                    f_ent = str(r.get("fecha_entrega") or "")[:10]
                    f_fac = str(r.get("fecha_factura") or "")[:10]
                    if f_fecha not in (f_ent, f_fac):
                        continue

                pat_r = str(r.get("patente") or "SIN ASIGNAR").strip().upper()
                if f_pat != "TODAS" and pat_r != f_pat:
                    continue

                st_r = str(r.get("status_entrega") or "PENDIENTE RUTA").strip().upper()
                if f_st != "TODOS" and st_r != f_st:
                    continue

                if q_txt and not any(
                    q_txt in str(r.get(c_k) or "").upper()
                    for c_k in ("numero_ov", "numero_factura", "cliente", "comuna", "direccion", "ejecutivo_ventas", "conductor", "patente")
                ):
                    continue

                filtrados.append(r)
            return filtrados

        def exportar_planilla_drivin(e=None):
            """1. Exporta el Excel oficial para carga en Drivin / Ruteo."""
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment

            lista = obtener_registros_filtrados() or list(registros_rutas_db)
            if not lista:
                notificar("No hay órdenes en la tabla para exportar a Drivin.", "#D97706")
                return

            try:
                os.makedirs("reportes_ruteo", exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                ruta_out = os.path.join("reportes_ruteo", f"Planilla_Drivin_Ruteo_{ts}.xlsx")

                filas = []
                for r in lista:
                    filas.append({
                        "Número OV": str(r.get("numero_ov") or ""),
                        "N° Factura": str(r.get("numero_factura") or ""),
                        "Fecha Entrega": str(r.get("fecha_entrega") or hoy_iso)[:10],
                        "Patente": str(r.get("patente") or "SIN ASIGNAR"),
                        "Conductor": str(r.get("conductor") or ""),
                        "Peoneta": str(r.get("peoneta_1") or ""),
                        "Vuelta": str(r.get("vuelta") or "AM"),
                        "Cliente": str(r.get("cliente") or ""),
                        "Requiere Agendamiento": "SÍ" if r.get("requiere_agendamiento") else "NO",
                        "Dirección": str(r.get("direccion") or ""),
                        "Comuna": str(r.get("comuna") or ""),
                        "Zona": str(r.get("zona") or ""),
                        "Bultos": str(r.get("etiqueta_bultos") or f"B {r.get('cantidad_bultos', 1)}"),
                        "Cantidad Bultos": int(r.get("cantidad_bultos") or 1),
                        "Peso (KG)": float(r.get("peso_kg") or 0.0),
                        "Sacos Arena": int(r.get("total_sacos_arena") or 0),
                        "Monto Neto": float(r.get("monto_neto") or 0.0),
                        "Ventana Horaria": str(r.get("ventana_horaria") or ""),
                        "Ejecutivo Ventas": str(r.get("ejecutivo_ventas") or ""),
                        "Nota Despacho": str(r.get("nota_despacho") or ""),
                    })

                df_out = pd.DataFrame(filas)
                with pd.ExcelWriter(ruta_out, engine="openpyxl") as writer:
                    df_out.to_excel(writer, sheet_name="Drivin_Ruteo", index=False)

                wb = openpyxl.load_workbook(ruta_out)
                ws = wb.active
                fill_hdr = PatternFill(fill_type="solid", start_color="0F766E", end_color="0F766E")
                font_hdr = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                ws.row_dimensions[1].height = 24
                for cell in ws[1]:
                    cell.fill = fill_hdr
                    cell.font = font_hdr
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                for col in ws.columns:
                    max_len = max(len(str(c.value or "")) for c in col)
                    ws.column_dimensions[col[0].column_letter].width = min(42, max(12, max_len + 4))
                wb.save(ruta_out)

                descargar_archivo_web(ruta_out, f"Planilla Drivin ({len(filas)} OVs)")
            except Exception as ex:
                notificar(f"Error exportando Planilla Drivin: {ex}", "#B91C1C")

        def exportar_hoja_ruta_y_arenas(e=None, formato_pdf: bool = False):
            """2. Exporta Hoja de Ruta + Matriz Oficial de los 24 SKUs de Arenas en Excel (.xlsx) o PDF imprimible."""
            from fpdf import FPDF
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment

            lista = obtener_registros_filtrados() or list(registros_rutas_db)
            if not lista:
                notificar("No hay órdenes para generar la Hoja de Ruta y Papeleta de Arenas.", "#D97706")
                return

            try:
                os.makedirs("reportes_ruteo", exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                fecha_emision = datetime.now().strftime("%d-%m-%Y %H:%M")
                ruta_xlsx = os.path.join("reportes_ruteo", f"Hoja_Ruta_y_Papeleta_Arenas_{ts}.xlsx")
                ruta_pdf = os.path.join("reportes_ruteo", f"Hoja_Ruta_y_Papeleta_Arenas_{ts}.pdf")

                filas_hoja_ruta = []
                filas_matriz_arenas = []
                totales_por_sku_arena = {sku_a: 0 for sku_a in SKUS_ARENAS_OFICIALES}
                total_kilos_ruta = 0.0
                total_bultos_ruta = 0

                for r in lista:
                    ov_s = str(r.get("numero_ov") or "")
                    fac_s = str(r.get("numero_factura") or "")
                    pat_s = str(r.get("patente") or "SIN ASIGNAR")
                    chof_s = str(r.get("conductor") or "")
                    peo_s = str(r.get("peoneta_1") or "")
                    vuelta_s = str(r.get("vuelta") or "AM")
                    cli_s = str(r.get("cliente") or "")
                    dir_s = str(r.get("direccion") or "")
                    com_s = str(r.get("comuna") or "")
                    peso_k = float(r.get("peso_kg") or 0.0)
                    cant_b = int(r.get("cantidad_bultos") or 1)
                    total_kilos_ruta += peso_k
                    total_bultos_ruta += cant_b

                    det_ar = r.get("detalle_arenas") or {}
                    if isinstance(det_ar, str):
                        try:
                            det_ar = json.loads(det_ar)
                        except Exception:
                            det_ar = {}

                    resumen_ar_txt = ", ".join(f"{k}:{v}" for k, v in det_ar.items() if int(v or 0) > 0)

                    filas_hoja_ruta.append({
                        "Patente": pat_s,
                        "Conductor": chof_s,
                        "Peoneta": peo_s,
                        "Vuelta": vuelta_s,
                        "Fecha Entrega": str(r.get("fecha_entrega") or hoy_iso)[:10],
                        "OV": ov_s,
                        "Factura": fac_s,
                        "Cliente": cli_s,
                        "Dirección": dir_s,
                        "Comuna": com_s,
                        "Bultos / Pallet": str(r.get("etiqueta_bultos") or f"B {cant_b}"),
                        "Peso (KG)": peso_k,
                        "Total Sacos Arena": int(r.get("total_sacos_arena") or 0),
                        "Detalle Arenas": resumen_ar_txt or "SIN ARENAS",
                        "Nota / Ventana": str(r.get("nota_despacho") or ""),
                        "Firma Recepción": "",
                    })

                    fila_ar = {
                        "Patente": pat_s,
                        "Conductor": chof_s,
                        "OV": ov_s,
                        "Factura": fac_s,
                        "Cliente": cli_s[:30],
                        "Comuna": com_s,
                        "Total_Sacos_OV": int(r.get("total_sacos_arena") or 0),
                    }
                    for sku_a in SKUS_ARENAS_OFICIALES:
                        cant_sku = int(det_ar.get(sku_a, 0) or 0)
                        fila_ar[sku_a] = cant_sku
                        totales_por_sku_arena[sku_a] += cant_sku
                    filas_matriz_arenas.append(fila_ar)

                fila_totales = {
                    "Patente": "TOTAL CARGA",
                    "Conductor": "",
                    "OV": "",
                    "Factura": "",
                    "Cliente": "SUMA TOTAL DE SACOS POR SKU",
                    "Comuna": "",
                    "Total_Sacos_OV": sum(totales_por_sku_arena.values()),
                }
                for sku_a in SKUS_ARENAS_OFICIALES:
                    fila_totales[sku_a] = totales_por_sku_arena[sku_a]
                filas_matriz_arenas.append(fila_totales)

                if not formato_pdf:
                    with pd.ExcelWriter(ruta_xlsx, engine="openpyxl") as writer:
                        pd.DataFrame(filas_hoja_ruta).to_excel(writer, sheet_name="1_Hoja_de_Ruta", index=False)
                        pd.DataFrame(filas_matriz_arenas).to_excel(writer, sheet_name="2_Papeleta_Arenas_24_SKUs", index=False)

                    wb = openpyxl.load_workbook(ruta_xlsx)
                    fill_hdr = PatternFill(fill_type="solid", start_color="1E3A8A", end_color="1E3A8A")
                    font_hdr = Font(name="Calibri", size=10.5, bold=True, color="FFFFFF")
                    for ws in wb.worksheets:
                        ws.row_dimensions[1].height = 24
                        for cell in ws[1]:
                            cell.fill = fill_hdr
                            cell.font = font_hdr
                            cell.alignment = Alignment(horizontal="center", vertical="center")
                    wb.save(ruta_xlsx)
                    descargar_archivo_web(ruta_xlsx, f"Hoja de Ruta + Papeleta Arenas ({len(filas_hoja_ruta)} OVs)")
                else:
                    pdf = FPDF(orientation="L", unit="mm", format="A4")
                    pdf.set_auto_page_break(auto=True, margin=12)
                    pdf.add_page()

                    pdf.set_fill_color(15, 23, 42)
                    pdf.rect(0, 0, 297, 22, style="F")
                    pdf.set_text_color(255, 255, 255)
                    pdf.set_font("Helvetica", "B", 14)
                    pdf.set_xy(10, 4)
                    pdf.cell(277, 6, txt="LUDIPEK WMS - HOJA DE RUTA OFICIAL Y PAPELETA DE CARGA DE ARENAS")
                    pdf.set_font("Helvetica", "", 9.5)
                    pdf.set_xy(10, 12)
                    pdf.cell(
                        277,
                        5,
                        txt=_texto_pdf_seguro(
                            f"Emision: {fecha_emision}  |  OVs: {len(filas_hoja_ruta)}  |  Bultos: {total_bultos_ruta}  |  Peso Total: {total_kilos_ruta:,.1f} kg  |  Total Sacos Arena: {sum(totales_por_sku_arena.values())}"
                        ),
                    )
                    pdf.set_text_color(0, 0, 0)

                    pdf.set_xy(10, 26)
                    pdf.set_fill_color(30, 58, 138)
                    pdf.set_text_color(255, 255, 255)
                    pdf.set_font("Helvetica", "B", 8)
                    pdf.cell(22, 7, "PATENTE", border=1, align="C", fill=True)
                    pdf.cell(22, 7, "OV / FACT", border=1, align="C", fill=True)
                    pdf.cell(58, 7, "CLIENTE", border=1, fill=True)
                    pdf.cell(52, 7, "DIRECCION / COMUNA", border=1, fill=True)
                    pdf.cell(18, 7, "BULTOS", border=1, align="C", fill=True)
                    pdf.cell(18, 7, "PESO KG", border=1, align="C", fill=True)
                    pdf.cell(55, 7, "DETALLE ARENAS", border=1, fill=True)
                    pdf.cell(32, 7, "FIRMA RECIBO", border=1, align="C", fill=True, ln=True)

                    pdf.set_text_color(0, 0, 0)
                    pdf.set_font("Helvetica", "", 7.5)
                    for fr in filas_hoja_ruta:
                        tiene_ar = fr["Total Sacos Arena"] > 0
                        pdf.set_fill_color(254, 243, 199) if tiene_ar else pdf.set_fill_color(255, 255, 255)
                        pdf.cell(22, 6.5, _texto_pdf_seguro(f"{fr['Patente']} {fr['Vuelta']}")[:13], border=1, align="C", fill=tiene_ar)
                        pdf.cell(22, 6.5, _texto_pdf_seguro(f"{fr['OV']} {fr['Factura']}")[:13], border=1, align="C", fill=tiene_ar)
                        pdf.cell(58, 6.5, _texto_pdf_seguro(fr["Cliente"])[:32], border=1, fill=tiene_ar)
                        pdf.cell(52, 6.5, _texto_pdf_seguro(f"{fr['Comuna']} - {fr['Dirección']}")[:29], border=1, fill=tiene_ar)
                        pdf.cell(18, 6.5, _texto_pdf_seguro(fr["Bultos / Pallet"])[:10], border=1, align="C", fill=tiene_ar)
                        pdf.cell(18, 6.5, f"{fr['Peso (KG)']:.1f}", border=1, align="C", fill=tiene_ar)
                        pdf.cell(55, 6.5, _texto_pdf_seguro(fr["Detalle Arenas"])[:30], border=1, fill=tiene_ar)
                        pdf.cell(32, 6.5, "", border=1, align="C", fill=tiene_ar, ln=True)

                    # Resumen inferior de sacos de arena por SKU para carga de grúa
                    skus_con_sacos = [(k, v) for k, v in totales_por_sku_arena.items() if v > 0]
                    if skus_con_sacos:
                        pdf.ln(5)
                        pdf.set_font("Helvetica", "B", 9.5)
                        pdf.cell(277, 6, txt="RESUMEN PAPELETA DE CARGA DE ARENAS POR SKU (TOTAL CAMION / RUTA):", ln=True)
                        pdf.set_font("Helvetica", "B", 8.5)
                        resumen_linea = "   |   ".join(f"{k}: {v} sacos" for k, v in skus_con_sacos)
                        pdf.multi_cell(277, 6, txt=_texto_pdf_seguro(resumen_linea), border=1)

                    pdf.output(ruta_pdf)
                    descargar_archivo_web(ruta_pdf, f"PDF Hoja de Ruta + Arenas ({len(filas_hoja_ruta)} OVs)")
            except Exception as ex:
                notificar(f"Error exportando Hoja de Ruta y Arenas: {ex}", "#B91C1C")

        def exportar_reporte_diario_sla(e=None):
            """3. Exporta el Reporte Diario de Entregas, SLA 36h/72h (sin domingos), Resumen por Camión e Incidencias."""
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment

            lista = obtener_registros_filtrados() or list(registros_rutas_db)
            if not lista:
                notificar("No hay registros para exportar el Reporte Diario SLA.", "#D97706")
                return

            try:
                os.makedirs("reportes_ruteo", exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                ruta_out = os.path.join("reportes_ruteo", f"Reporte_Diario_SLA_OTIF_{ts}.xlsx")

                filas_sla = []
                resumen_camiones = {}

                for r in lista:
                    f_crea = str(r.get("fecha_creacion_ov") or "")[:10]
                    f_aprob = str(r.get("fecha_aprobacion_ov") or f_crea)[:10]
                    f_ent = str(r.get("fecha_entrega") or hoy_iso)[:10]
                    dias_hab, c36, c72 = calcular_dias_habiles_sla(f_aprob, f_ent)
                    pat_c = str(r.get("patente") or "SIN ASIGNAR")
                    peso_c = float(r.get("peso_kg") or 0.0)
                    monto_c = float(r.get("monto_neto") or 0.0)
                    sacos_c = int(r.get("total_sacos_arena") or 0)

                    filas_sla.append({
                        "OV": str(r.get("numero_ov") or ""),
                        "N° Factura": str(r.get("numero_factura") or ""),
                        "Fecha Creación OV": f_crea,
                        "Fecha Aprobación OV": f_aprob,
                        "Fecha Factura": str(r.get("fecha_factura") or "")[:10],
                        "Fecha Entrega": f_ent,
                        "Cliente": str(r.get("cliente") or ""),
                        "Requiere Agendamiento": "SÍ" if r.get("requiere_agendamiento") else "NO",
                        "Comuna": str(r.get("comuna") or ""),
                        "Zona": str(r.get("zona") or ""),
                        "Patente": pat_c,
                        "Tipo Flota": str(r.get("tipo_flota") or "Distribución Propia"),
                        "Conductor": str(r.get("conductor") or ""),
                        "Vuelta": str(r.get("vuelta") or "AM"),
                        "Peso (KG)": peso_c,
                        "Bultos": str(r.get("etiqueta_bultos") or "B 1"),
                        "Sacos Arena": sacos_c,
                        "Monto Neto": monto_c,
                        "Status Entrega": str(r.get("status_entrega") or "PENDIENTE RUTA"),
                        "Recibido Por": str(r.get("recibido_por") or ""),
                        "Incidencia": str(r.get("incidencia") or "0"),
                        "Días Hábiles SLA": dias_hab,
                        "Cumple SLA 36h": c36,
                        "Cumple SLA 72h": c72,
                        "Ejecutivo Ventas": str(r.get("ejecutivo_ventas") or ""),
                    })

                    if pat_c not in resumen_camiones:
                        resumen_camiones[pat_c] = {
                            "Patente": pat_c,
                            "Conductor": str(r.get("conductor") or ""),
                            "Total_OVs": 0,
                            "Entregadas": 0,
                            "Peso_Total_KG": 0.0,
                            "Sacos_Arena": 0,
                            "Monto_Neto_Total": 0.0,
                        }
                    resumen_camiones[pat_c]["Total_OVs"] += 1
                    if str(r.get("status_entrega") or "").upper() == "ENTREGADO":
                        resumen_camiones[pat_c]["Entregadas"] += 1
                    resumen_camiones[pat_c]["Peso_Total_KG"] += peso_c
                    resumen_camiones[pat_c]["Sacos_Arena"] += sacos_c
                    resumen_camiones[pat_c]["Monto_Neto_Total"] += monto_c

                with pd.ExcelWriter(ruta_out, engine="openpyxl") as writer:
                    pd.DataFrame(filas_sla).to_excel(writer, sheet_name="1_Base_Entregas_SLA", index=False)
                    pd.DataFrame(list(resumen_camiones.values())).to_excel(writer, sheet_name="2_Resumen_Por_Camion", index=False)

                wb = openpyxl.load_workbook(ruta_out)
                fill_hdr = PatternFill(fill_type="solid", start_color="1E3A8A", end_color="1E3A8A")
                font_hdr = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                for ws in wb.worksheets:
                    ws.row_dimensions[1].height = 24
                    for cell in ws[1]:
                        cell.fill = fill_hdr
                        cell.font = font_hdr
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                wb.save(ruta_out)

                descargar_archivo_web(ruta_out, f"Reporte Diario SLA y Entregas ({len(filas_sla)} OVs)")
            except Exception as ex:
                notificar(f"Error exportando Reporte Diario SLA: {ex}", "#B91C1C")

        # =====================================================================
        # RENDERIZADO DE LAS 4 TABLAS Y CÁLCULO DE KPIs EN VIVO
        # =====================================================================
        def renderizar_tablas_ruteo(e=None):
            checks_seleccion_ov.clear()
            filtrados = obtener_registros_filtrados()

            total_ovs = len(filtrados)
            facturadas_cnt = sum(1 for r in filtrados if str(r.get("numero_factura") or "").strip() not in ("", "0", "NONE"))
            kilos_tot = sum(float(r.get("peso_kg") or 0.0) for r in filtrados)
            sacos_ar_tot = sum(int(r.get("total_sacos_arena") or 0) for r in filtrados)

            evaluados_sla = 0
            cumplen_36 = 0
            for r in filtrados:
                f_ap = str(r.get("fecha_aprobacion_ov") or r.get("fecha_creacion_ov") or "")[:10]
                f_en = str(r.get("fecha_entrega") or "")[:10]
                _, c36, _ = calcular_dias_habiles_sla(f_ap, f_en)
                if c36 in ("Cumple", "No Cumple"):
                    evaluados_sla += 1
                    if c36 == "Cumple":
                        cumplen_36 += 1

            pct_otif = int(round((cumplen_36 / max(1, evaluados_sla)) * 100)) if evaluados_sla else 100

            lbl_kpi_total_ov.value = str(total_ovs)
            lbl_kpi_facturadas.value = str(facturadas_cnt)
            lbl_kpi_kilos_ruta.value = f"{kilos_tot:,.0f} kg"
            lbl_kpi_arenas_sacos.value = str(sacos_ar_tot)
            lbl_kpi_otif_36.value = f"{pct_otif}%"

            filas_t1 = []
            filas_t2 = []
            filas_t3 = []

            for r in filtrados:
                ov_cod = str(r.get("numero_ov") or "")
                fac_cod = str(r.get("numero_factura") or "").strip()
                cli_nom = str(r.get("cliente") or "")
                req_ag = bool(r.get("requiere_agendamiento"))
                dir_txt = str(r.get("direccion") or "")
                com_txt = str(r.get("comuna") or "SANTIAGO")
                zona_txt = str(r.get("zona") or "Zona-RM")
                monto_n = float(r.get("monto_neto") or 0.0)
                peso_k = float(r.get("peso_kg") or 0.0)
                etiq_b = str(r.get("etiqueta_bultos") or f"B {r.get('cantidad_bultos', 1)}")
                sacos_a = int(r.get("total_sacos_arena") or 0)
                pat_s = str(r.get("patente") or "SIN ASIGNAR")
                chof_s = str(r.get("conductor") or "-")
                vuelta_s = str(r.get("vuelta") or "AM")
                st_ent = str(r.get("status_entrega") or "PENDIENTE RUTA").upper()

                chk = ft.Checkbox(value=False, active_color=ACCENT_CYAN)
                checks_seleccion_ov[ov_cod] = (chk, r)

                det_ar = r.get("detalle_arenas") or {}
                if isinstance(det_ar, str):
                    try:
                        det_ar = json.loads(det_ar)
                    except Exception:
                        det_ar = {}
                resumen_ar = ", ".join(f"{k}({v})" for k, v in det_ar.items() if int(v or 0) > 0) or "-"

                # Fila para Tabla 1: Mesa de Facturación
                filas_t1.append(
                    ft.DataRow(
                        color="#2A2419" if req_ag else None,
                        cells=[
                            ft.DataCell(chk),
                            ft.DataCell(ft.Text(f"{ov_cod}\n{r.get('ola_picking', 'Corte 09:00')}", size=10.5, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN)),
                            ft.DataCell(
                                crear_badge_estado(fac_cod, "#065F46", "#D1FAE5")
                                if fac_cod
                                else crear_badge_estado("SIN FACTURA", "#92400E", "#FEF3C7")
                            ),
                            ft.DataCell(
                                ft.Text(
                                    f"{cli_nom[:28]}" + (" [AGENDAR]" if req_ag else ""),
                                    size=10.5,
                                    weight=ft.FontWeight.BOLD if req_ag else ft.FontWeight.NORMAL,
                                    color="#FBBF24" if req_ag else TEXT_WHITE,
                                )
                            ),
                            ft.DataCell(ft.Text(f"{dir_txt[:26]} • {com_txt}", size=10.5, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(zona_txt, size=10.5, weight=ft.FontWeight.BOLD, color="#A78BFA")),
                            ft.DataCell(ft.Text(f"${monto_n:,.0f}", size=10.5, weight=ft.FontWeight.BOLD, color="#34D399")),
                            ft.DataCell(ft.Text(f"{etiq_b} | {peso_k:.1f} kg", size=10.5, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(f"{sacos_a} sacos" if sacos_a > 0 else "-", size=10.5, weight=ft.FontWeight.BOLD, color="#FBBF24" if sacos_a > 0 else TEXT_MUTED)),
                            ft.DataCell(ft.Text(f"{str(r.get('ejecutivo_ventas') or '')[:14]} | {str(r.get('nota_despacho') or '')[:18]}", size=10, color=TEXT_MUTED)),
                            ft.DataCell(
                                boton_accion("EDITAR", ft.Icons.EDIT_OUTLINED, lambda ev, it=r: abrir_modal_editar_ov_completa(it), ACCENT_BLUE, height_val=26)
                            ),
                        ],
                    )
                )

                # Fila para Tabla 2: Planificador de Ruteo y Arenas
                chk_r2 = ft.Checkbox(
                    value=False,
                    active_color=ACCENT_CYAN,
                    on_change=lambda ev, k=ov_cod: setattr(checks_seleccion_ov[k][0], "value", ev.control.value) if k in checks_seleccion_ov else None,
                )
                filas_t2.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(chk_r2),
                            ft.DataCell(ft.Text(f"{pat_s} ({vuelta_s})", size=10.5, weight=ft.FontWeight.BOLD, color="#FBBF24" if pat_s != "SIN ASIGNAR" else TEXT_MUTED)),
                            ft.DataCell(ft.Text(chof_s[:18], size=10.5, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(f"OV {ov_cod} | F:{fac_cod or 'S/F'}", size=10.5, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(cli_nom[:26], size=10.5, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(f"{dir_txt[:22]} ({com_txt})", size=10.5, color=TEXT_WHITE)),
                            ft.DataCell(ft.Text(etiq_b, size=10.5, weight=ft.FontWeight.BOLD, color="#A78BFA")),
                            ft.DataCell(ft.Text(f"{peso_k:.1f} kg", size=10.5, weight=ft.FontWeight.BOLD, color="#34D399")),
                            ft.DataCell(ft.Text(resumen_ar[:28], size=10, color="#FBBF24" if sacos_a > 0 else TEXT_MUTED)),
                            ft.DataCell(
                                boton_accion("FICHA / ARENAS", ft.Icons.EDIT_NOTE_ROUNDED, lambda ev, it=r: abrir_modal_editar_ov_completa(it), "#334155", height_val=26)
                            ),
                        ]
                    )
                )

                # Fila para Tabla 3: Entregas y SLA 36h / 72h
                f_ap = str(r.get("fecha_aprobacion_ov") or r.get("fecha_creacion_ov") or "")[:10]
                f_en = str(r.get("fecha_entrega") or hoy_iso)[:10]
                dias_hab, c36, c72 = calcular_dias_habiles_sla(f_ap, f_en)
                badge_st = (
                    crear_badge_estado("ENTREGADO", "#065F46", "#D1FAE5")
                    if st_ent == "ENTREGADO"
                    else (
                        crear_badge_estado(st_ent, "#1E3A8A", "#DBEAFE")
                        if st_ent == "EN RUTA"
                        else crear_badge_estado(st_ent, "#92400E", "#FEF3C7")
                    )
                )
                filas_t3.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(f_en, size=10.5, weight=ft.FontWeight.BOLD, color="#34D399")),
                            ft.DataCell(ft.Text(f"{pat_s} ({chof_s[:14]})", size=10.5, color="#FBBF24")),
                            ft.DataCell(ft.Text(f"{ov_cod} / {fac_cod or '-'}", size=10.5, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(f"{cli_nom[:24]} ({com_txt})", size=10.5, color=TEXT_WHITE)),
                            ft.DataCell(badge_st),
                            ft.DataCell(ft.Text(str(r.get("recibido_por") or "-"), size=10.5, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(str(r.get("incidencia") or "0"), size=10.5, color="#F87171" if str(r.get("incidencia") or "0") != "0" else TEXT_MUTED)),
                            ft.DataCell(
                                ft.Text(
                                    f"{dias_hab}d | 36h:{c36} | 72h:{c72}",
                                    size=10,
                                    weight=ft.FontWeight.BOLD,
                                    color="#34D399" if c36 == "Cumple" else "#F87171",
                                )
                            ),
                            ft.DataCell(
                                ft.Row(
                                    [
                                        boton_accion("ENTREGADO ✓", ft.Icons.CHECK_CIRCLE_OUTLINE, lambda ev, it=r: cambiar_estado_entrega_rapido(it, "ENTREGADO"), "#047857", height_val=26),
                                        boton_accion("INCIDENCIA", ft.Icons.WARNING_AMBER_ROUNDED, lambda ev, it=r: abrir_modal_editar_ov_completa(it), "#B45309", height_val=26),
                                    ],
                                    spacing=4,
                                    tight=True,
                                )
                            ),
                        ]
                    )
                )

            tabla_mesa_facturacion.rows = filas_t1
            tabla_ruteo_drivin.rows = filas_t2
            tabla_entregas_sla.rows = filas_t3
            self.page.update()

        def cargar_datos_ruteo_y_facturacion(e=None):
            nonlocal registros_rutas_db
            bodega_act = obtener_bodega_activa(self.page)
            cargar_maestras_flota_y_zonas()
            try:
                res = supabase.table("wms_despacho_rutas").select("*").order("id", desc=True).limit(500).execute()
                registros_rutas_db = [r for r in (res.data or []) if coincide_bodega(r, bodega_act)]
            except Exception as ex:
                print(f"[WARN] Error leyendo wms_despacho_rutas: {ex}")
                registros_rutas_db = []
            renderizar_tablas_ruteo()

        txt_filtro_fecha.on_change = renderizar_tablas_ruteo
        dd_filtro_patente.on_change = renderizar_tablas_ruteo
        dd_filtro_status.on_change = renderizar_tablas_ruteo
        txt_buscar_general.on_change = renderizar_tablas_ruteo

        def marcar_desmarcar_visibles(estado_bool: bool):
            for _, (chk, _) in checks_seleccion_ov.items():
                chk.value = estado_bool
            self.page.update()

        # =====================================================================
        # COMPOSICIÓN VISUAL DE LAS 4 SUB-VISTAS DEL MÓDULO
        # =====================================================================
        barra_kpis_y_filtros = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    caja_kpi_ruteo(lbl_kpi_total_ov, "Total OVs en Vista", ACCENT_TEAL),
                                    caja_kpi_ruteo(lbl_kpi_facturadas, "Con Factura NS", ACCENT_CYAN),
                                    caja_kpi_ruteo(lbl_kpi_kilos_ruta, "Peso Total (KG)", "#F59E0B"),
                                    caja_kpi_ruteo(lbl_kpi_arenas_sacos, "Sacos de Arena", "#8B5CF6"),
                                    caja_kpi_ruteo(lbl_kpi_otif_36, "Cumplimiento SLA 36h", "#10B981"),
                                ],
                                spacing=8,
                                wrap=True,
                            ),
                            ft.Row(
                                [
                                    boton_accion(
                                        "SUBIR EXCEL BASE NS",
                                        ft.Icons.UPLOAD_FILE_ROUNDED,
                                        lambda e: picker_excel_ns.pick_files(allowed_extensions=["xlsx", "xlsm", "xls"]),
                                        "#6D28D9",
                                        height_val=34,
                                    ),
                                    boton_accion("PLANILLA DRIVIN", ft.Icons.LOCAL_SHIPPING_OUTLINED, exportar_planilla_drivin, "#0F766E", height_val=34),
                                    boton_accion("RUTA + ARENAS (XLSX)", ft.Icons.TABLE_VIEW_OUTLINED, lambda e: exportar_hoja_ruta_y_arenas(e, formato_pdf=False), "#B45309", height_val=34),
                                    boton_accion("PAPELETA ARENAS (PDF)", ft.Icons.PICTURE_AS_PDF_OUTLINED, lambda e: exportar_hoja_ruta_y_arenas(e, formato_pdf=True), "#DC2626", height_val=34),
                                    boton_accion("REPORTE DIARIO SLA", ft.Icons.ASSESSMENT_OUTLINED, exportar_reporte_diario_sla, "#1E3A8A", height_val=34),
                                ],
                                spacing=6,
                                wrap=True,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=6),
                    ft.Row(
                        [
                            txt_filtro_fecha,
                            boton_accion("📅 CALENDARIO", ft.Icons.CALENDAR_MONTH_ROUNDED, abrir_calendario_filtro, "#1E3A8A", height_val=32),
                            boton_accion("TODAS FECHAS", ft.Icons.EVENT_REPEAT_ROUNDED, lambda e: (setattr(txt_filtro_fecha, "value", ""), renderizar_tablas_ruteo()), "#334155", height_val=32),
                            dd_filtro_patente,
                            dd_filtro_status,
                            txt_buscar_general,
                            boton_accion("MARCAR TODAS", ft.Icons.CHECK_BOX_OUTLINED, lambda e: marcar_desmarcar_visibles(True), "#334155", height_val=32),
                            boton_accion("DESMARCAR", ft.Icons.CHECK_BOX_OUTLINE_BLANK, lambda e: marcar_desmarcar_visibles(False), "#475569", height_val=32),
                            boton_accion("SINCRONIZAR PACKING / NS", ft.Icons.SYNC_ROUNDED, sincronizar_ovs_desde_packing_y_netsuite, ACCENT_BLUE, height_val=32),
                        ],
                        spacing=8,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=8,
            )
        )

        # SUB-VISTA 1: MESA DE FACTURACIÓN Y CRUCE NETSUITE
        self.sub_facturacion = ft.Column(
            [
                barra_kpis_y_filtros,
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Text("1. MESA DE FACTURACIÓN, AGENDAMIENTO Y BULTOS (MULTI-PC EN TIEMPO REAL)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            cont_t1,
                        ],
                        spacing=6,
                    )
                ),
            ],
            spacing=10,
        )

        # SUB-VISTA 2: PLANIFICADOR DE RUTEO Y PAPELETA DE ARENAS
        panel_asignacion_camion = tarjeta_dark(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.LOCAL_SHIPPING_ROUNDED, color="#FBBF24", size=20),
                            ft.Text("ASIGNACIÓN DE CAMIÓN, CONDUCTOR Y VUELTA A OVs SELECCIONADAS:", size=12.5, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            lbl_capacidad_camion,
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            dd_asignar_patente,
                            txt_asignar_chofer,
                            txt_asignar_peoneta1,
                            dd_asignar_vuelta,
                            txt_asignar_fecha_ent,
                            boton_accion("ASIGNAR CAMIÓN A OVs MARCADAS", ft.Icons.SEND_ROUNDED, asignar_camion_a_ovs_seleccionadas, "#047857", height_val=34),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                ],
                spacing=8,
            )
        )

        self.sub_ruteo = ft.Column(
            [
                barra_kpis_y_filtros,
                panel_asignacion_camion,
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Text("2. PLANIFICADOR DE RUTEO DRIVIN, CONTROL DE KILOS Y PAPELETA DE 24 SKUs DE ARENAS", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            cont_t2,
                        ],
                        spacing=6,
                    )
                ),
            ],
            spacing=10,
        )

        # SUB-VISTA 3: REPORTE DIARIO DE ENTREGAS Y SLA (36H / 72H)
        self.sub_sla_diario = ft.Column(
            [
                barra_kpis_y_filtros,
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Text("3. SEGUIMIENTO DIARIO DE ENTREGAS, INCIDENCIAS Y CUMPLIMIENTO SLA 36H / 72H (SIN DOMINGOS)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            cont_t3,
                        ],
                        spacing=6,
                    )
                ),
            ],
            spacing=10,
        )

        # SUB-VISTA 4: MAESTRA DE FLOTA Y CONDUCTORES (CON FORMULARIO CRUD)
        self.sub_flota = ft.Column(
            [
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Text("AGREGAR O ACTUALIZAR CAMIÓN EN LA MAESTRA DE FLOTA:", size=12.5, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
                            ft.Row(
                                [
                                    txt_flota_patente,
                                    txt_flota_conductor,
                                    txt_flota_peoneta,
                                    dd_flota_tipo,
                                    txt_flota_cap_kg,
                                    boton_accion("GUARDAR CAMIÓN", ft.Icons.SAVE_ROUNDED, guardar_camion_flota, "#047857", height_val=34),
                                ],
                                spacing=8,
                                wrap=True,
                            ),
                        ],
                        spacing=8,
                    )
                ),
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Text("4. MAESTRA OFICIAL DE FLOTA, CONDUCTORES Y CAPACIDAD EN KILOS", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            cont_t4,
                        ],
                        spacing=6,
                    )
                ),
            ],
            spacing=10,
        )

        self.contenedor = ft.Container(content=self.sub_facturacion)

        barra_titulo = ft.Container(
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            bgcolor="#222A2C",
            border_radius=8,
            border=ft.Border.all(1, BORDER_COLOR),
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.LOCAL_SHIPPING_OUTLINED, color=ACCENT_CYAN, size=22),
                            ft.Text("MÓDULO 7: FACTURACIÓN, RUTEO DRIVIN, PAPELETA DE ARENAS & SLA DIARIO", size=14.5, weight=ft.FontWeight.W_900, color=TEXT_WHITE),
                        ],
                        spacing=10,
                    ),
                    ft.Row(
                        [
                            boton_accion("1. MESA FACTURACIÓN", ft.Icons.RECEIPT_LONG_ROUNDED, lambda e: self.sel_sub_ruteo(0), ACCENT_TEAL, height_val=28),
                            boton_accion("2. RUTEO & ARENAS", ft.Icons.LOCAL_SHIPPING_OUTLINED, lambda e: self.sel_sub_ruteo(1), "#1E3A8A", height_val=28),
                            boton_accion("3. ENTREGAS & SLA", ft.Icons.VERIFIED_OUTLINED, lambda e: self.sel_sub_ruteo(2), "#047857", height_val=28),
                            boton_accion("4. FLOTA CAMIONES", ft.Icons.BADGE_OUTLINED, lambda e: self.sel_sub_ruteo(3), "#475569", height_val=28),
                        ],
                        spacing=6,
                        wrap=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                wrap=True,
            ),
        )

        col_principal = ft.Column(
            [
                barra_titulo,
                self.contenedor,
            ],
            spacing=10,
            scroll=ft.ScrollMode.ALWAYS,
            expand=True,
        )

        self.vista = ft.Container(
            padding=ft.Padding.only(left=12, top=10, right=16, bottom=12),
            bgcolor=BG_MODULO,
            content=col_principal,
            expand=True,
        )
        self.cargar_datos_ruteo_func = cargar_datos_ruteo_y_facturacion

    def cargar_datos_ruteo(self, e=None):
        self.cargar_datos_ruteo_func(e)

    def sel_sub_ruteo(self, idx: int):
        vistas = [self.sub_facturacion, self.sub_ruteo, self.sub_sla_diario, self.sub_flota]
        self.contenedor.content = vistas[idx if 0 <= idx < len(vistas) else 0]
        self.cargar_datos_ruteo_func()
        self.page.update()