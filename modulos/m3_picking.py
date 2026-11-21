import os
import json
import shutil
import inspect
import urllib.parse
from datetime import datetime
import pandas as pd
import flet as ft
from dependencias import *


def depurar_lineas_traslado(df):
    """Deja una línea por ítem en órdenes de traslado (TrnfrOrd) de NetSuite.

    NetSuite guarda cada ítem de un traslado en varias líneas internas; se conservan
    las de salida (cantidad negativa) y, si no vienen, se eliminan repeticiones exactas.
    """
    if df is None or getattr(df, "empty", True) or "tipo_doc" not in df.columns:
        return df
    es_to = df["tipo_doc"].astype(str).str.strip() == "TrnfrOrd"
    if not es_to.any():
        return df
    partes = [df[~es_to]]
    for _, grupo in df[es_to].groupby("numero_ov", sort=False):
        if "cantidad_raw" in grupo.columns:
            negativos = grupo[pd.to_numeric(grupo["cantidad_raw"], errors="coerce") < 0]
            if not negativos.empty:
                grupo = negativos
        partes.append(grupo.drop_duplicates(subset=["sku", "cantidad"], keep="first"))
    return pd.concat(partes, ignore_index=True)


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

        # --- 2. VARIABLES DE ESTADO Y FUNCIONES AUXILIARES BASE ---
        olas_extraidas_ns = []
        checks_liberacion = {}
        checks_facturacion = {}
        registros_packing_db = []
        registros_locales_mem = []
        filtro_corte_activo = "TODOS"
        filtro_dia_ov_activo = "TODOS"
        filtro_canal_ov_activo = "TODOS"
        Archivo_Meta_Despacho = "config_despacho_packing.json"

        def notificar(texto: str, color: str = "#0284C7"):
            from dependencias import notificar_global
            notificar_global(self.page, texto, color)

        # DEFINICIÓN PRIMORDIAL DE boton_primario ANTES DE SU USO
        def boton_primario(texto: str, icono, on_click, color_bg: str, height_val: int = 30, width_val=None):
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

        def cargar_meta_despacho() -> dict:
            if os.path.exists(Archivo_Meta_Despacho):
                try:
                    with open(Archivo_Meta_Despacho, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    return {}
            return {}

        # --- 3. PRUEBA CONTROLADA: EXCEL TRASLADO -> PACKING RF ---
        # Temporal: permite validar la subida del Excel y Packing sin modificar el resto del WMS.
        MODO_PRUEBA_EXCEL_A_PACKING = False
        def procesar_excel_traslado_scl_ccp(ruta_excel: str):
            """Crea una OT trazable en Supabase y la deja disponible para Picking RF."""
            id_ot_db = None
            try:
                df_tras = pd.read_excel(ruta_excel, sheet_name="Traslado", header=2)

                # Consolidar SKU repetidos para no crear dos líneas RF del mismo artículo.
                lineas_por_sku = {}
                for _, row in df_tras.iterrows():
                    sku_raw = row.get("Artículo")
                    if pd.isna(sku_raw):
                        continue
                    sku = str(sku_raw).strip().upper()
                    if not sku or sku == "NAN" or "TOTAL" in sku:
                        continue
                    try:
                        cant = int(float(row.get("SCL a CCP (Un)", 0) or 0))
                    except (TypeError, ValueError):
                        cant = 0
                    if cant <= 0:
                        continue
                    desc = str(row.get("Descripción") or "TRASLADO SCL-CCP").strip().upper()
                    if sku not in lineas_por_sku:
                        lineas_por_sku[sku] = {"sku": sku, "descripcion": desc, "cantidad": 0}
                    lineas_por_sku[sku]["cantidad"] += cant

                lineas_ot = list(lineas_por_sku.values())
                total_unidades = sum(x["cantidad"] for x in lineas_ot)
                if not lineas_ot:
                    notificar("El Excel no contiene cantidades SCL a CCP mayores que cero.", "#D97706")
                    return

                bodega_act = obtener_bodega_activa(self.page)

                # Número legible y único. Se verifica en Supabase por si hay dos cargas simultáneas.
                prefijo_ot = "OT-CCP-"
                ultimo = 0
                existentes = (supabase.table("netsuite_ordenes_venta")
                               .select("numero_ov")
                               .ilike("numero_ov", f"{prefijo_ot}%")
                               .order("id", desc=True).limit(500).execute())
                for fila_existente in (existentes.data or []):
                    valor = str(fila_existente.get("numero_ov") or "").strip().upper()
                    sufijo = valor[len(prefijo_ot):] if valor.startswith(prefijo_ot) else ""
                    if sufijo.isdigit():
                        ultimo = max(ultimo, int(sufijo))
                num_ot = f"{prefijo_ot}{ultimo + 1:04d}"

                # Sin operador: el supervisor reparte la cola desde Monitor de usuarios (equipos de trabajo).
                operador_elegido = None

                payload_ot = {
                    "bodega": bodega_act,
                    "id_externo_ns": num_ot,
                    "numero_ov": num_ot,
                    "cliente_nombre": "BODEGA CONCEPCION (TRASLADO SCL-CCP)",
                    "canal_venta": "TRASLADO SCL-CCP",
                    "fecha_emision_ns": datetime.now().isoformat(),
                    # En esta prueba se omite Picking para validar directamente Packing móvil.
                    "estado_ns": "PENDIENTE_PACKING" if MODO_PRUEBA_EXCEL_A_PACKING else "PENDIENTE_PICKING",
                    "operador_asignado": operador_elegido,
                }
                res_ins = supabase.table("netsuite_ordenes_venta").insert(payload_ot).execute()
                if not res_ins.data:
                    raise RuntimeError("Supabase no devolvió el encabezado de la OT creada")

                id_ot_db = res_ins.data[0].get("id")
                if id_ot_db is None:
                    raise RuntimeError("La OT fue insertada sin ID de Supabase")

                lote_detalles = [{
                    "orden_id": int(id_ot_db),
                    "linea_ns": idx,
                    "sku": lin["sku"],
                    "cantidad_pedida": int(lin["cantidad"]),
                    "cantidad_comprometida": int(lin["cantidad"]),
                    "cantidad_pickeada": int(lin["cantidad"]) if MODO_PRUEBA_EXCEL_A_PACKING else 0,
                    "lote_asignado": "",
                    "estado_linea": "PICKEADO" if MODO_PRUEBA_EXCEL_A_PACKING else "PENDIENTE",
                    "lotes_pickeados": "",
                } for idx, lin in enumerate(lineas_ot, start=1)]

                res_det = supabase.table("netsuite_detalle_ov").insert(lote_detalles).execute()
                if not res_det.data:
                    raise RuntimeError("No se pudieron registrar las líneas de la OT")

                destino_prueba = "PACKING RF" if MODO_PRUEBA_EXCEL_A_PACKING else "PICKING RF"
                notificar(
                    f"OT {num_ot} creada y lista en {destino_prueba}: "
                    f"{len(lineas_ot)} SKU(s), {total_unidades} UN. "
                    f"Busque este número exacto en el celular.",
                    "#047857",
                )
                cargar_monitor_packing_dual()

            except Exception as ex:
                # Compensación: evita dejar una cabecera huérfana si fallan sus líneas.
                if id_ot_db is not None:
                    try:
                        supabase.table("netsuite_detalle_ov").delete().eq("orden_id", id_ot_db).execute()
                        supabase.table("netsuite_ordenes_venta").delete().eq("id", id_ot_db).execute()
                    except Exception:
                        pass
                notificar(f"Error creando OT de traslado en Supabase: {ex}", "#B91C1C")

        # Carga de Excel de traslado compatible con Flet 1.x.
        # FilePicker se registra como Service y conserva el nombre original.
        archivo_traslado_subiendo = {"nombre": None}

        async def al_seleccionar_excel_traslado(e):
            archivos = getattr(e, "files", None)
            if not archivos:
                notificar("Selección cancelada.", "#D97706")
                return

            f_obj = archivos[0]
            ruta_local = getattr(f_obj, "path", None)
            if ruta_local and os.path.isfile(ruta_local):
                procesar_excel_traslado_scl_ccp(ruta_local)
                return

            nombre = os.path.basename(str(getattr(f_obj, "name", "Concepcion.xlsx")))
            archivo_traslado_subiendo["nombre"] = nombre

            datos = getattr(f_obj, "bytes", None)
            if datos:
                raiz_proyecto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                destino = os.path.join(raiz_proyecto, "assets", "uploads", nombre)
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                with open(destino, "wb") as fh:
                    fh.write(bytes(datos))
                procesar_excel_traslado_scl_ccp(destino)
                return

            try:
                url_subida = self.page.get_upload_url(nombre, 600)
                archivo_upload = ft.FilePickerUploadFile(
                    upload_url=url_subida,
                    name=nombre,
                )
                resultado = picker_excel_traslado.upload([archivo_upload])
                if inspect.isawaitable(resultado):
                    await resultado
                notificar(f"Subiendo {nombre}...", "#0284C7")
            except Exception as ex:
                notificar(f"Error subiendo Excel: {ex}", "#B91C1C")

        async def on_result_traslado_event(e):
            await al_seleccionar_excel_traslado(e)

        async def on_upload_traslado_event(e):
            error_subida = getattr(e, "error", None)
            if error_subida:
                notificar(f"Error durante la subida del Excel: {error_subida}", "#B91C1C")
                return

            progreso = float(getattr(e, "progress", 0) or 0)
            if progreso < 1:
                return

            # En Flet 1.x, e.name puede ser solamente 'upload'.
            nombre_original = str(
                archivo_traslado_subiendo.get("nombre")
                or getattr(e, "file_name", None)
                or ""
            ).strip()
            if not nombre_original or nombre_original.lower() in ("upload", "/upload", "none"):
                notificar("La carga terminó, pero no se pudo recuperar el nombre original del Excel.", "#B91C1C")
                return
            nombre_original = os.path.basename(nombre_original)

            raiz_proyecto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            carpetas_busqueda = []
            for carpeta in (
                os.path.join(raiz_proyecto, "assets", "uploads"),
                os.path.join(os.getcwd(), "assets", "uploads"),
                os.path.join(raiz_proyecto, "uploads"),
                os.path.join(os.getcwd(), "uploads"),
            ):
                carpeta_abs = os.path.abspath(carpeta)
                if carpeta_abs not in carpetas_busqueda:
                    carpetas_busqueda.append(carpeta_abs)

            ruta_encontrada = None
            for carpeta in carpetas_busqueda:
                candidata = os.path.join(carpeta, nombre_original)
                if os.path.isfile(candidata):
                    ruta_encontrada = candidata
                    break

            # Respaldo: buscar por nombre y, si Flet cambió el nombre, tomar el XLSX
            # más reciente creado después de iniciar la carga.
            if not ruta_encontrada:
                candidatos_xlsx = []
                for carpeta in carpetas_busqueda:
                    if not os.path.isdir(carpeta):
                        continue
                    for raiz_busqueda, _, archivos in os.walk(carpeta):
                        for archivo in archivos:
                            ruta_archivo = os.path.join(raiz_busqueda, archivo)
                            if archivo.lower() == nombre_original.lower():
                                ruta_encontrada = ruta_archivo
                                break
                            if archivo.lower().endswith((".xlsx", ".xls")):
                                try:
                                    candidatos_xlsx.append((os.path.getmtime(ruta_archivo), ruta_archivo))
                                except OSError:
                                    pass
                        if ruta_encontrada:
                            break
                    if ruta_encontrada:
                        break
                if not ruta_encontrada and candidatos_xlsx:
                    candidatos_xlsx.sort(reverse=True)
                    ruta_encontrada = candidatos_xlsx[0][1]

            if not ruta_encontrada:
                notificar(
                    f"El Excel terminó de subir, pero no fue encontrado. "
                    f"Nombre esperado: {nombre_original}. Carpetas revisadas: "
                    f"{', '.join(carpetas_busqueda)}",
                    "#B91C1C",
                )
                return

            notificar(
                f"Excel recibido. Procesando hoja Traslado: {os.path.basename(ruta_encontrada)}",
                "#0284C7",
            )
            procesar_excel_traslado_scl_ccp(ruta_encontrada)

        _params_fp = inspect.signature(ft.FilePicker.__init__).parameters
        _kw_fp = {}
        if "on_result" in _params_fp:
            _kw_fp["on_result"] = on_result_traslado_event
        if "on_upload" in _params_fp:
            _kw_fp["on_upload"] = on_upload_traslado_event
        picker_excel_traslado = ft.FilePicker(**_kw_fp)
        if picker_excel_traslado not in self.page.services:
            self.page.services.append(picker_excel_traslado)

        async def abrir_selector_traslado(e=None):
            # Antes el botón no tenía on_click y no abría nada
            try:
                kw = {"allow_multiple": False, "allowed_extensions": ["xlsx", "xls"]}
                if "with_data" in inspect.signature(picker_excel_traslado.pick_files).parameters:
                    kw["with_data"] = True
                res = picker_excel_traslado.pick_files(**kw)
                if inspect.isawaitable(res):
                    res = await res
                    if res is not None:
                        from types import SimpleNamespace
                        await al_seleccionar_excel_traslado(SimpleNamespace(files=getattr(res, "files", res)))
            except Exception as ex:
                notificar(f"No se pudo abrir el selector de archivos: {ex}", "#B91C1C")

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
                            ft.Text("Haga clic en 'DESCARGAR ARCHIVO AHORA' para guardarlo en su PC:", size=11, color=TEXT_MUTED),
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
                    [ft.Row([tabla], scroll=ft.ScrollMode.ALWAYS, vertical_alignment=ft.CrossAxisAlignment.START)],
                    scroll=ft.ScrollMode.ALWAYS,
                    expand=True,
                ),
            )

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
                content=ft.Container(content=ft.Text(text, color=TEXT_WHITE, size=12), alignment=ft.Alignment.CENTER_LEFT),
            )

        def dropdown_dark(
            label: str = "",
            width: int = None,
            expand=None,
            value: str = None,
            options: list = None,
            on_change=None,
            on_select=None,
            hint_text: str = None,
        ):
            opts = [
                opt_w(o.key, o.text) if isinstance(o, ft.DropdownOption) and not o.content else o
                for o in (options or [])
            ]
            dd = ft.Dropdown(
                label=label,
                hint_text=hint_text,
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
            # En Flet 0.70+ Dropdown solo dispara on_select: on_change se redirige ahí
            if on_select is not None:
                dd.on_select = on_select
            elif on_change is not None:
                dd.on_select = on_change
            return dd

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
                        content=txt_control,
                    ),
                    ft.Text(etiqueta_inf, size=10, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=3,
            )

        def crear_indicador_circulo_etapa(estado_etapa: str, texto_etapa: str):
            if estado_etapa == "COMPLETADO":
                bg_c, bd_c, col_t, bg_chip = "#10B981", "#34D399", "#34D399", "#064E3B"
                ico_int = ft.Icon(ft.Icons.CHECK_ROUNDED, color="#FFFFFF", size=12)
            elif estado_etapa == "EN_PROCESO":
                bg_c, bd_c, col_t, bg_chip = "#F59E0B", "#FDE68A", "#FBBF24", "#451A03"
                ico_int = ft.Container(width=8, height=8, border_radius=4, bgcolor="#FFFFFF")
            else:
                bg_c, bd_c, col_t, bg_chip = "#1E293B", "#475569", "#64748B", "#141A1C"
                ico_int = None

            circulo = ft.Container(
                width=18,
                height=18,
                border_radius=9,
                bgcolor=bg_c,
                border=ft.Border.all(1.8, bd_c),
                alignment=ft.Alignment.CENTER,
                content=ico_int,
            )
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                bgcolor=bg_chip,
                border_radius=16,
                border=ft.Border.all(1, bd_c if estado_etapa != "ESPERA" else "#2B3537"),
                content=ft.Row([circulo, ft.Text(texto_etapa, size=10.5, weight=ft.FontWeight.BOLD, color=col_t)], spacing=7, tight=True),
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
            return ">13:00"

        # --- 5. CONTROLES VISUALES, CALENDARIO Y CONTADORES DIGITALES ---
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
            label="Filtrar por Corte",
            width=165,
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

        # Filtro por día: un botón en el resumen y otro en seguimiento comparten el mismo filtro
        etiquetas_dia = []

        def refrescar_etiquetas_dia():
            for lbl in etiquetas_dia:
                lbl.value = "Todas las fechas" if filtro_dia_ov_activo == "TODOS" else f"Día {filtro_dia_ov_activo}"
                lbl.color = UI["texto"] if filtro_dia_ov_activo == "TODOS" else UI["exito"]
            for b in botones_limpiar_dia:
                b.visible = filtro_dia_ov_activo != "TODOS"

        def al_elegir_fecha_calendario(e):
            nonlocal filtro_dia_ov_activo
            val_dt = getattr(e.control, "value", None)
            if val_dt:
                filtro_dia_ov_activo = val_dt.strftime("%Y-%m-%d") if hasattr(val_dt, "strftime") else str(val_dt)[:10]
                refrescar_etiquetas_dia()
                renderizar_monitor_cortes_y_tablas()

        selector_calendario_ov = ft.DatePicker(
            first_date=datetime(2024, 1, 1),
            last_date=datetime(2030, 12, 31),
            help_text="DÍA DE LAS ÓRDENES",
            cancel_text="Cancelar",
            confirm_text="Filtrar",
            on_change=al_elegir_fecha_calendario,
        )
        try:
            self.page.overlay.append(selector_calendario_ov)
        except Exception:
            pass

        def abrir_calendario_ov(e=None):
            try:
                self.page.open(selector_calendario_ov)
            except Exception:
                try:
                    self.page.show_dialog(selector_calendario_ov)
                except Exception:
                    selector_calendario_ov.open = True
                    self.page.update()

        def limpiar_fecha_calendario_ov(e=None):
            nonlocal filtro_dia_ov_activo
            filtro_dia_ov_activo = "TODOS"
            refrescar_etiquetas_dia()
            renderizar_monitor_cortes_y_tablas()

        botones_limpiar_dia = []

        def crear_boton_dia():
            lbl = ft.Text("Todas las fechas", size=12, weight=ft.FontWeight.W_600, color=UI["texto"])
            etiquetas_dia.append(lbl)
            btn = ft.Container(
                height=36,
                padding=ft.Padding.symmetric(horizontal=12, vertical=0),
                border=ft.Border.all(1, UI["borde"]),
                border_radius=6,
                ink=True,
                tooltip="Filtrar las órdenes por día",
                on_click=abrir_calendario_ov,
                content=ft.Row([ft.Icon(ft.Icons.CALENDAR_MONTH_OUTLINED, size=18, color=UI["acento"]), lbl],
                               spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )
            limpiar = ft.IconButton(icon=ft.Icons.CLOSE_ROUNDED, icon_size=18, icon_color=UI["texto_2"],
                                    tooltip="Quitar filtro de día", on_click=limpiar_fecha_calendario_ov, visible=False)
            botones_limpiar_dia.append(limpiar)
            return btn, limpiar

        btn_abrir_calendario_ov, btn_limpiar_dia = crear_boton_dia()
        btn_dia_resumen, btn_limpiar_dia_resumen = crear_boton_dia()

        dd_filtro_canal_ov = dropdown_dark(
            label="Canal",
            width=170,
            value="TODOS",
            options=[
                opt_w("TODOS", "Todos los canales"),
                opt_w("NORMAL", "Normal"),
                opt_w("FARMACIA", "Farmacia (-FA)"),
            ],
        )
        dd_filtro_corte.label = "Corte"
        dd_filtro_corte.width = 150
        dd_filtro_corte.options = [
            opt_w("TODOS", "Todos los cortes"),
            opt_w("09:00", "09:00 hrs"),
            opt_w("10:00", "10:00 hrs"),
            opt_w("12:00", "12:00 hrs"),
            opt_w("13:00", "13:00 hrs"),
            opt_w(">13:00", "Después de 13:00"),
        ]
        dd_filtro_etapa = dropdown_dark(
            label="Etapa",
            width=190,
            value="TODAS",
            options=[
                opt_w("TODAS", "Todas las etapas"),
                opt_w("0", "En picking"),
                opt_w("1", "En packing"),
                opt_w("2", "En facturación / tránsito"),
                opt_w("3", "Facturada / recibida"),
            ],
        )

        txt_buscar_ov_unificada = texto_dark(label="Buscar OV, cliente, comuna o LPN")
        txt_estado_erp = ft.Text(
            "Conexión directa con NetSuite activa." if NETSUITE_CONECTADO else "Sin conexión directa a NetSuite: se usan las órdenes de Supabase.",
            size=11,
            color=UI["exito"] if NETSUITE_CONECTADO else UI["alerta"],
        )

        lbl_kpi_total_ovs = ft.Text("0")
        lbl_kpi_picking = ft.Text("0")
        lbl_kpi_packing = ft.Text("0")
        lbl_kpi_fact = ft.Text("0")
        lbl_det_total = ft.Text("", size=11, color=UI["texto_3"])
        lbl_det_fact = ft.Text("", size=11, color=UI["texto_3"])
        col_cortes_resumen = ft.Column(spacing=8, tight=True)
        lbl_conteo_seguimiento = ft.Text("", size=12, color=UI["texto_2"])
        lbl_resumen_prev = ft.Text("Sin órdenes extraídas", size=12, color=UI["texto_2"])

        def tabla_base(columnas: list, fila_alta: int = 44):
            return ft.DataTable(
                heading_row_color=UI["card_alt"],
                heading_row_height=40,
                data_row_min_height=fila_alta,
                data_row_max_height=fila_alta + 8,
                column_spacing=22,
                horizontal_margin=14,
                divider_thickness=0.5,
                show_checkbox_column=False,
                columns=[ft.DataColumn(ft.Text(c, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"])) for c in columnas],
                rows=[],
            )

        def contenedor_tabla(tabla: ft.DataTable, altura: int):
            # Igual que ui_tabla, pero su alto lo calcula este módulo según la ventana
            return ft.Container(
                height=altura,
                border=ft.Border.all(1, UI["borde"]),
                border_radius=8,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=ft.Column(
                    [ft.Row([tabla], scroll=ft.ScrollMode.AUTO, vertical_alignment=ft.CrossAxisAlignment.START)],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
            )

        tabla_previsualizacion_ns = tabla_base(["", "OV", "Fecha", "Corte", "Canal (toque para cambiar)", "Cliente", "Líneas", "Unidades", ""], 40)
        tabla_listado_unico_ovs = tabla_base(["OV / OT", "Canal", "Fecha · corte", "Cliente", "Pickeado", "Etapa", "Bultos", ""])
        txt_buscar_facturacion = texto_dark(label="Buscar OV, cliente, comuna o LPN", width=320)
        sw_ver_ya_facturadas = ft.Switch(label="Incluir facturadas", value=False, active_color=UI["exito"])
        lbl_resumen_facturacion = ft.Text("", size=12, color=UI["texto_2"])
        tabla_facturacion_ns = tabla_base(["", "OV / OT", "Canal", "Fecha", "Cliente", "Comuna", "Bultos", "Unidades", "Estado", ""])

        cont_tabla_prev_ns = contenedor_tabla(tabla_previsualizacion_ns, 420)
        cont_tabla_listado_unico = contenedor_tabla(tabla_listado_unico_ovs, 520)
        cont_tabla_facturacion = contenedor_tabla(tabla_facturacion_ns, 520)

        # --- 7. CONEXIÓN Y SINCRONIZACIÓN CON SUPABASE ---
        def detectar_es_farmacia_texto(*textos) -> bool:
            for t in textos:
                s = str(t or "").strip().upper()
                if s and ("-FA" in s or s.endswith("FA") or "BOEHRINGER" in s or "PICK-FARM" in s or "FARMACIA" in s):
                    return True
            return False

        def extraer_campos_registro_ola(r: dict, mapa_clientes_ns: dict = None, mapa_meta_desp: dict = None) -> dict:
            ov_val = str(r.get("numero_ov") or r.get("orden_venta") or r.get("ov") or r.get("id_externo_ns") or "").strip().upper().replace("OV ", "").strip()
            if not ov_val or ov_val in ("NONE", "NULL", "-"):
                return None

            cli_val = str(r.get("cliente_nombre") or r.get("cliente") or r.get("nombre_cliente") or r.get("razon_social") or "").strip()
            ov_limpia = ov_val.replace("-FA", "").strip()
            if cli_val.upper() == "CLIENTE B2B" or (ov_limpia.isdigit() and len(ov_limpia) <= 4 and not r.get("numero_ov")):
                return None

            if not cli_val or cli_val.upper() in ("NONE", "NULL", "-"):
                cli_val = (mapa_clientes_ns or {}).get(ov_val) or (mapa_clientes_ns or {}).get(ov_limpia) or "CLIENTE REGISTRADO"

            est_val = str(
                r.get("estado_ns")
                or r.get("estado_wms")
                or r.get("estado")
                or r.get("estado_packing")
                or r.get("estado_picking")
                or r.get("estado_sanitario")
                or "PENDIENTE_PICKING"
            ).strip().upper()

            if est_val in ("EMPACADO", "COMPLETADO"):
                est_val = "PENDIENTE_FACTURACION"

            canal_val = str(r.get("canal_venta") or r.get("tipo_ola") or r.get("canal") or "").strip().upper()
            es_fa = bool(r.get("es_farmacia")) or detectar_es_farmacia_texto(ov_val, canal_val, r.get("sku"), r.get("descripcion"))
            if es_fa and not ov_val.endswith("-FA") and not ov_val.startswith("OT-"):
                ov_val = f"{ov_val}-FA"

            ts_val = r.get("corte_horario") or r.get("hora_corte") or r.get("corte") or r.get("fecha_emision_ns") or r.get("created_at")
            corte_str = clasificar_corte_horario(ts_val) if ts_val else clasificar_corte_horario(None)

            raw_fecha_ov = str(r.get("fecha_emision_ns") or r.get("fecha_ov") or r.get("created_at") or "").strip()
            fecha_ov_str = raw_fecha_ov[:10] if len(raw_fecha_ov) >= 10 else datetime.now().strftime("%Y-%m-%d")

            try:
                unid_val = int(float(r.get("unidades") or r.get("unidades_totales") or r.get("total_unidades") or r.get("cantidad") or 1))
            except Exception:
                unid_val = 1

            meta_ov = dict((mapa_meta_desp or {}).get(ov_val) or (mapa_meta_desp or {}).get(ov_limpia) or {})
            for parte in str(r.get("canal_venta") or "").split("|"):
                clave, _, valor = parte.partition(":")
                clave = clave.strip().upper()
                if valor.strip() and clave in ("BULTOS", "TIPO", "COMUNA", "LPN", "PESO_KG", "FALTANTE", "MOTIVO_FALTANTE"):
                    meta_ov[{"TIPO": "tipo_empaque"}.get(clave, clave.lower())] = valor.strip()
            comuna_str = str(r.get("comuna") or meta_ov.get("comuna") or ("CONCEPCIÓN" if "CONCEPCION" in cli_val.upper() else "SANTIAGO")).strip().upper()
            tipo_emp_str = str(meta_ov.get("tipo_empaque") or "BULTO").strip().upper()
            try:
                bultos_cnt = int(float(meta_ov.get("bultos") or 1))
            except Exception:
                bultos_cnt = 1
            lpn_str = str(meta_ov.get("lpn") or f"LPN-PK-{ov_limpia}").strip().upper()

            return {
                "raw": r,
                "id": r.get("id"),
                "ov": ov_val,
                "ov_base": ov_limpia,
                "fecha_ov": fecha_ov_str,
                "cliente": cli_val,
                "comuna": comuna_str,
                "tipo_empaque": tipo_emp_str,
                "bultos": bultos_cnt,
                "lpn": lpn_str,
                "mesa": str(r.get("mesa_packing") or "").strip().upper(),
                # Cierre de packing con faltante (script 10): unidades que no viajaron y motivo
                "faltante": int(float(meta_ov.get("faltante") or 0)) if str(meta_ov.get("faltante") or "0").replace(".", "").isdigit() else 0,
                "motivo_faltante": str(meta_ov.get("motivo_faltante") or ""),
                "estado": est_val,
                "es_farmacia": es_fa,
                "corte": corte_str,
                "unidades": unid_val,
                "unidades_pickeadas": int(float(r.get("unidades_pickeadas") or r.get("cantidad_pickeada") or 0)),
                "lineas_detalle": [],
            }

        def recargar_datos_supabase():
            nonlocal registros_packing_db
            agrupado_por_ov = {}
            mapa_meta_desp = cargar_meta_despacho()

            mapa_maestra_sku = {}
            try:
                filas_maestra = leer_tabla_paginada(lambda: supabase.table("maestra_sku").select("*"))
                for m in filas_maestra:
                    s_k = str(m.get("sku") or "").strip().upper()
                    if not s_k:
                        continue
                    ean_val = m.get("codigo_barras") or m.get("ean") or m.get("ean_base") or m.get("gtin") or ""
                    info_sku_m = {
                        "descripcion": str(m.get("descripcion") or m.get("nombre") or "").strip(),
                        "ean": str(ean_val or "").strip(),
                    }
                    mapa_maestra_sku[s_k] = info_sku_m
                    s_base = s_k.split("-")[0].strip()
                    if s_base and s_base not in mapa_maestra_sku:
                        mapa_maestra_sku[s_base] = info_sku_m
            except Exception:
                pass

            for item_mem in registros_locales_mem:
                ov_m = str(item_mem.get("ov") or "").removesuffix("-FA").strip()
                if ov_m:
                    agrupado_por_ov[ov_m] = dict(item_mem)

            mapa_clientes_ns = {}
            for item_ns in olas_extraidas_ns:
                k_ov = str(item_ns.get("ov") or "").strip().upper()
                cli_ns = str(item_ns.get("cliente") or "").strip()
                if k_ov and cli_ns:
                    mapa_clientes_ns[k_ov] = cli_ns
                    mapa_clientes_ns[k_ov.replace("-FA", "")] = cli_ns

            mapa_id_a_ov_base = {}
            bodega_act = obtener_bodega_activa(self.page)
            try:
                # Se leen las 600 OV MÁS RECIENTES (antes eran las más antiguas) y se procesan en orden ascendente
                res_ov = supabase.table("netsuite_ordenes_venta").select("*").order("id", desc=True).limit(600).execute()
                filas_ov = [r for r in reversed(res_ov.data or []) if coincide_bodega(r, bodega_act)]
                for r in filas_ov:
                    info = extraer_campos_registro_ola(dict(r), mapa_clientes_ns, mapa_meta_desp)
                    if not info:
                        continue
                    ov_b = info["ov_base"]
                    if r.get("id") is not None:
                        mapa_id_a_ov_base[r.get("id")] = ov_b
                    agrupado_por_ov[ov_b] = info
            except Exception:
                pass

            # Datos de despacho guardados por el cierre de packing (script 12): mandan sobre canal_venta y el JSON local
            try:
                ids_cargados = list(mapa_id_a_ov_base.keys())
                for dsp in (leer_por_lista("wms_despacho_ov", "orden_id", ids_cargados) if ids_cargados else []):
                    ov_d = mapa_id_a_ov_base.get(dsp.get("orden_id"))
                    if ov_d and ov_d in agrupado_por_ov:
                        reg = agrupado_por_ov[ov_d]
                        reg["bultos"] = int(dsp.get("bultos") or reg.get("bultos") or 1)
                        reg["tipo_empaque"] = str(dsp.get("tipo_empaque") or reg.get("tipo_empaque") or "BULTO").upper()
                        reg["comuna"] = str(dsp.get("comuna") or reg.get("comuna") or "SANTIAGO").upper()
                        if dsp.get("lpn"):
                            reg["lpn"] = str(dsp.get("lpn")).upper()
                        reg["faltante"] = int(dsp.get("faltante_un") or 0)
                        reg["motivo_faltante"] = str(dsp.get("motivo_faltante") or "")
                        reg["peso_kg"] = dsp.get("peso_real_kg") or dsp.get("peso_esperado_kg")
            except Exception as ex_dsp:
                print(f"[WARN] wms_despacho_ov (¿script 12 ejecutado?): {ex_dsp}")

            mapa_lineas_pl_por_ov = {}
            mapa_pallets_pl_por_ov = {}
            try:
                res_pl = supabase.table("wms_packing_lists_fa").select("*").order("id", desc=True).limit(300).execute()
                for pl in (res_pl.data or []):
                    if not coincide_bodega(pl, bodega_act):
                        continue
                    ov_pl_raw = str(pl.get("numero_ov") or "").strip().upper()
                    if not ov_pl_raw:
                        continue
                    ov_pl_base = ov_pl_raw.split("(")[0].split("|")[0].strip().removesuffix("-FA").strip()

                    det_json = pl.get("detalle_json")
                    if isinstance(det_json, str):
                        try:
                            det_json = json.loads(det_json)
                        except Exception:
                            det_json = []

                    lineas_pl = []
                    meta_desde_json = {}
                    estado_packing_json = ""
                    if isinstance(det_json, list):
                        for item_j in det_json:
                            if isinstance(item_j, dict):
                                estado_item = str(item_j.get("_estado_packing") or "").strip().upper()
                                if estado_item:
                                    estado_packing_json = estado_item
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
                                linea_pl = {
                                    "sku": sku_j,
                                    "ean": str(item_j.get("ean") or inf_m.get("ean") or "").strip(),
                                    "descripcion": str(item_j.get("descripcion") or inf_m.get("descripcion") or "").strip(),
                                    "cantidad": int(float(item_j.get("solicitado") or 0)),
                                    "cantidad_pedida": int(float(item_j.get("solicitado") or 0)),
                                    "cantidad_pickeada": int(float(item_j.get("pickeado") or item_j.get("unidades_totales") or 0)),
                                    "unidades_totales": int(float(item_j.get("unidades_totales") or item_j.get("pickeado") or 0)),
                                    "cajas": int(float(item_j.get("cajas") or 0)),
                                    "displays": int(float(item_j.get("displays") or 0)),
                                    "multiplo_aplicado": int(float(item_j.get("multiplo_aplicado") or 1)),
                                    "lpn_pallet": str(item_j.get("lpn_pallet") or item_j.get("lpn_consolidado") or "").strip().upper(),
                                    "lote": str(item_j.get("lote") or "S/L").strip().upper(),
                                    "fecha_vencimiento_cl": str(item_j.get("fecha_vencimiento_cl") or "S/F").strip(),
                                    "lotes": str(item_j.get("lotes") or "").strip(),
                                    "es_farmacia": True,
                                }
                                lineas_pl.append(linea_pl)
                                lpn_p = linea_pl["lpn_pallet"]
                                if lpn_p:
                                    mapa_pallets_pl_por_ov.setdefault(ov_pl_base, {}).setdefault(lpn_p, []).append(linea_pl)

                    if lineas_pl and ov_pl_base not in mapa_lineas_pl_por_ov:
                        mapa_lineas_pl_por_ov[ov_pl_base] = lineas_pl
                    if ov_pl_base in agrupado_por_ov:
                        agrupado_por_ov[ov_pl_base]["pallets_detalle"] = mapa_pallets_pl_por_ov.get(ov_pl_base, {})
                        agrupado_por_ov[ov_pl_base]["packing_persistido"] = bool(mapa_pallets_pl_por_ov.get(ov_pl_base))
                        agrupado_por_ov[ov_pl_base]["estado_packing_json"] = estado_packing_json

                    if ov_pl_base in agrupado_por_ov and meta_desde_json:
                        if meta_desde_json.get("comuna"):
                            agrupado_por_ov[ov_pl_base]["comuna"] = str(meta_desde_json["comuna"]).upper()
                        if meta_desde_json.get("tipo_empaque"):
                            agrupado_por_ov[ov_pl_base]["tipo_empaque"] = str(meta_desde_json["tipo_empaque"]).upper()
                        if meta_desde_json.get("bultos"):
                            agrupado_por_ov[ov_pl_base]["bultos"] = int(meta_desde_json["bultos"])
                        if meta_desde_json.get("lpn"):
                            agrupado_por_ov[ov_pl_base]["lpn"] = str(meta_desde_json["lpn"]).upper()
            except Exception:
                pass

            try:
                # Detalle de las OV cargadas (por orden_id, paginado) + últimas 1000 líneas como respaldo
                try:
                    filas_det_por_id = leer_por_lista("netsuite_detalle_ov", "orden_id", list(mapa_id_a_ov_base.keys()))
                except Exception as ex_det:
                    print(f"[WARN] Detalle OV por orden_id: {ex_det}")
                    filas_det_por_id = []
                res_det_recientes = supabase.table("netsuite_detalle_ov").select("*").order("id", desc=True).limit(1000).execute()
                filas_det = {d.get("id"): d for d in (res_det_recientes.data or []) + filas_det_por_id}
                ovs_con_detalle_db = set()
                for d in sorted(filas_det.values(), key=lambda x: x.get("id") or 0):
                    ord_id = d.get("orden_id")
                    ov_b = mapa_id_a_ov_base.get(ord_id) or str(d.get("numero_ov") or "").strip().upper().removesuffix("-FA").strip()
                    if not ov_b or ov_b not in agrupado_por_ov:
                        continue
                    if ov_b not in ovs_con_detalle_db:
                        agrupado_por_ov[ov_b]["lineas_detalle"] = []
                        ovs_con_detalle_db.add(ov_b)

                    sku_d = str(d.get("sku") or "-").strip().upper()
                    sku_d_base = sku_d.split("-")[0].strip()
                    info_m = mapa_maestra_sku.get(sku_d) or mapa_maestra_sku.get(sku_d_base) or {}
                    respaldo_pl = next(
                        (x for x in mapa_lineas_pl_por_ov.get(ov_b, []) if x["sku"] == sku_d or x["sku"].split("-")[0].strip() == sku_d_base),
                        {},
                    )

                    desc_d = str(d.get("descripcion") or info_m.get("descripcion") or respaldo_pl.get("descripcion") or "").strip()
                    ean_d = str(d.get("ean") or info_m.get("ean") or respaldo_pl.get("ean") or "").strip()
                    cant_ped = int(float(d.get("cantidad_pedida") or d.get("cantidad_comprometida") or respaldo_pl.get("cantidad_pedida") or 0))
                    cant_pick = max(int(float(d.get("cantidad_pickeada") or 0)), int(float(respaldo_pl.get("cantidad_pickeada") or 0)))

                    lotes_d = str(d.get("lotes_pickeados") or d.get("lote_asignado") or "").strip()
                    if lotes_d.upper() in ("NONE", "NULL", ""):
                        lotes_d = str(respaldo_pl.get("lotes") or "").strip()

                    agrupado_por_ov[ov_b]["lineas_detalle"].append({
                        "id_detalle": d.get("id"),
                        "linea_ns": d.get("linea_ns"),
                        "sku": sku_d,
                        "ean": ean_d,
                        "descripcion": desc_d,
                        "cantidad": cant_ped,
                        "cantidad_pedida": cant_ped,
                        "cantidad_pickeada": cant_pick,
                        "lotes": lotes_d,
                        "es_farmacia": agrupado_por_ov[ov_b].get("es_farmacia", False),
                    })

                for ov_c in ovs_con_detalle_db:
                    lins = agrupado_por_ov[ov_c]["lineas_detalle"]
                    agrupado_por_ov[ov_c]["unidades"] = sum(x.get("cantidad_pedida", 0) for x in lins)
                    agrupado_por_ov[ov_c]["unidades_pickeadas"] = sum(x.get("cantidad_pickeada", 0) for x in lins)
            except Exception:
                pass

            registros_packing_db = sorted(
                agrupado_por_ov.values(),
                key=lambda x: (str(x.get("fecha_ov") or ""), int(x.get("id") or 0)),
                reverse=True,
            )

        def cambiar_filtro_estado_interno(corte_sel: str):
            nonlocal filtro_corte_activo
            filtro_corte_activo = "TODOS" if filtro_corte_activo == corte_sel else corte_sel
            dd_filtro_corte.value = filtro_corte_activo

        def construir_barra_corte(etiqueta_corte: str, cant_ovs: int, cant_listas: int, max_escala: int, fn_click_corte=None):
            altura_max_px = 86
            ratio = min(1.0, cant_ovs / max(1, max_escala))
            alto_barra = max(12, int(ratio * altura_max_px)) if cant_ovs > 0 else 6
            color_b = "#10B981" if (cant_ovs > 0 and cant_listas >= cant_ovs) else (ACCENT_BLUE if cant_ovs > 0 else "#334155")

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
                        content=ft.Container(width=38, height=alto_barra, bgcolor=color_b, border_radius=4),
                    ),
                    ft.Text(etiqueta_corte, size=10, color=ACCENT_CYAN if filtro_corte_activo == etiqueta_corte else TEXT_MUTED, weight=ft.FontWeight.BOLD),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=3,
            )

        def cambiar_estado_ov_db(info_item: dict, nuevo_estado: str):
            ov_cod = str(info_item.get("ov") or "").strip().upper()
            ov_sin_fa = ov_cod.removesuffix("-FA").strip()
            info_item["estado"] = nuevo_estado
            for col_ov in ("estado_ns", "estado"):
                try:
                    supabase.table("netsuite_ordenes_venta").update({col_ov: nuevo_estado}).or_(
                        f"numero_ov.eq.{ov_cod},numero_ov.eq.{ov_sin_fa}"
                    ).execute()
                    break
                except Exception:
                    continue

        def descargar_pdf_contenido_pallets(info_ov: dict):
            from fpdf import FPDF
            pallets = info_ov.get("pallets_detalle") or {}
            if not pallets:
                notificar("La OV no tiene detalle de pallets transferido desde Packing RF.", "#D97706")
                return
            try:
                ov_cod = str(info_ov.get("ov") or "S-OV").strip().upper()
                os.makedirs("reportes_packing", exist_ok=True)
                ruta_pdf = os.path.join("reportes_packing", f"Contenido_Pallets_{ov_cod.replace('/', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
                pdf = FPDF(orientation="L", unit="mm", format="A4")
                pdf.set_auto_page_break(auto=True, margin=12)
                for lpn, lineas_pallet in pallets.items():
                    pdf.add_page()
                    pdf.set_fill_color(15, 118, 110); pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 15)
                    pdf.cell(0, 11, "LUDIPEK WMS - CONTENIDO DE PALLET", ln=True, fill=True, align="C")
                    pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 13)
                    pdf.cell(0, 9, f"LPN: {lpn}   |   OV/OT: {ov_cod}", ln=True)
                    pdf.set_font("Arial", "", 9)
                    pdf.cell(0, 6, f"Cliente: {str(info_ov.get('cliente') or 'CLIENTE')[:90]}", ln=True)
                    total_un = sum(int(x.get("unidades_totales") or x.get("cantidad_pickeada") or 0) for x in lineas_pallet)
                    total_cj = sum(int(x.get("cajas") or 0) for x in lineas_pallet)
                    total_dsp = sum(int(x.get("displays") or 0) for x in lineas_pallet)
                    pdf.cell(0, 6, f"Resumen: {len(lineas_pallet)} SKU | {total_cj} cajas | {total_dsp} displays | {total_un} unidades", ln=True)
                    pdf.ln(2)
                    headers = [("SKU", 28), ("Descripcion", 82), ("Lote", 38), ("Vencimiento", 28), ("Cajas", 18), ("Displays", 20), ("Unidades", 22), ("Multiplo", 20)]
                    pdf.set_font("Arial", "B", 8); pdf.set_fill_color(30, 58, 138); pdf.set_text_color(255, 255, 255)
                    for titulo, ancho in headers: pdf.cell(ancho, 7, titulo, border=1, fill=True, align="C")
                    pdf.ln(); pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
                    for item in lineas_pallet:
                        valores = [str(item.get("sku") or "")[:16], str(item.get("descripcion") or "")[:48], str(item.get("lote") or "S/L")[:22], str(item.get("fecha_vencimiento_cl") or "S/F")[:14], str(item.get("cajas") or 0), str(item.get("displays") or 0), str(item.get("unidades_totales") or item.get("cantidad_pickeada") or 0), str(item.get("multiplo_aplicado") or 1)]
                        for valor, (_, ancho) in zip(valores, headers): pdf.cell(ancho, 7, valor, border=1, align="C" if ancho <= 28 else "L")
                        pdf.ln()
                pdf.output(ruta_pdf)
                descargar_archivo_web(ruta_pdf, f"PDF contenido de pallets - {ov_cod}")
            except Exception as ex:
                notificar(f"Error generando PDF de pallets: {ex}", "#B91C1C")

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

        def mostrar_modal_detalle_ov(ov_num: str, info_ov: dict):
            lineas_det = info_ov.get("lineas_detalle", [])
            filas = []
            for ld in lineas_det:
                cant_sol = int(ld.get("cantidad_pedida") or ld.get("cantidad") or 0)
                cant_pk = int(ld.get("cantidad_pickeada") or 0)
                color = UI["exito"] if cant_sol and cant_pk >= cant_sol else (UI["alerta"] if cant_pk else UI["texto_2"])
                filas.append(ft.Container(
                    padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                    border=ft.Border(bottom=ft.BorderSide(0.5, UI["borde"])),
                    content=ft.Row([
                        ft.Column([
                            ft.Text(str(ld.get("sku", "-")), size=12.5, weight=ft.FontWeight.W_700, color=UI["texto"]),
                            ft.Text(str(ld.get("descripcion") or ""), size=11.5, color=UI["texto_2"], max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            *([ft.Text(f"Lotes: {ld.get('lotes')}", size=11, color=UI["texto_3"])] if str(ld.get("lotes") or "").strip() else []),
                        ], spacing=1, expand=True, tight=True),
                        ft.Text(f"{cant_pk} / {cant_sol} UN", size=12.5, weight=ft.FontWeight.W_700, color=color),
                    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                ))
            if not filas:
                filas.append(ft.Text("Esta orden no tiene líneas cargadas.", size=12, color=UI["texto_2"]))

            def cerrar_d(ev=None):
                try:
                    page.pop_dialog()
                except Exception:
                    dlg_det.open = False
                page.update()

            aviso_faltante = (
                [ft.Container(
                    padding=10, border_radius=8, bgcolor=ft.Colors.with_opacity(0.12, UI["peligro"]),
                    border=ft.Border.all(1, UI["peligro"]),
                    content=ft.Text(f"Salió CON FALTANTE de {info_ov.get('faltante')} UN · motivo: {info_ov.get('motivo_faltante') or '-'}",
                                    size=12.5, weight=ft.FontWeight.W_600, color="#FCA5A5"),
                )] if info_ov.get("faltante") else []
            )
            datos = ft.Row([
                chip_canal(info_ov),
                chip(nombre_etapa(info_ov), COLORES_ETAPA[etapa_ov(info_ov.get("estado"))]),
                ft.Text(f"{info_ov.get('fecha_ov', '-')} · corte {info_ov.get('corte', '-')} · {info_ov.get('comuna') or 'SANTIAGO'}",
                        size=12, color=UI["texto_2"]),
            ], spacing=8, wrap=True)
            acciones = [ui_boton("Cerrar", None, cerrar_d, "texto")]
            if etapa_ov(info_ov.get("estado")) <= 1 and info_ov.get("id"):
                dd_mesa = dropdown_dark(
                    label="Mesa de packing", width=170, value=info_ov.get("mesa") or None,
                    options=[opt_w(f"MESA {i}", f"Mesa {i}") for i in range(1, 7)],
                )

                def guardar_mesa(ev=None):
                    if not dd_mesa.value:
                        return
                    try:
                        supabase.rpc("wms_asignar_mesa_packing", {
                            "p_orden_id": info_ov.get("id"), "p_mesa": dd_mesa.value,
                            "p_usuario": str(getattr(self.page, "usuario_actual", None) or "PC"),
                        }).execute()
                    except Exception as ex:
                        notificar(f"No se pudo cambiar la mesa: {ex}", "#B91C1C")
                        return
                    cerrar_d()
                    notificar(f"{ov_num} quedó en {dd_mesa.value.capitalize()}.", "#047857")
                    cargar_monitor_packing_dual()

                dd_mesa.on_select = guardar_mesa
                acciones.insert(0, dd_mesa)
            if info_ov.get("pallets_detalle"):
                acciones.insert(0, ui_boton("PDF pallets", ft.Icons.PICTURE_AS_PDF_OUTLINED,
                                            lambda ev: (cerrar_d(), descargar_pdf_contenido_pallets(info_ov)), "secundario"))
            acciones[0:0] = [
                ui_boton("Packing list", ft.Icons.TABLE_VIEW_OUTLINED, lambda ev: (cerrar_d(), exportar_ov_farmacia_excel_pdf(info_ov)), "secundario"),
                ui_boton("Etiquetas de bultos", ft.Icons.QR_CODE_2_ROUNDED, lambda ev: (cerrar_d(), imprimir_etiqueta_packing_bultos_ov(info_ov))),
            ]
            dlg_det = ft.AlertDialog(
                title=ft.Column([
                    ft.Text(f"{ov_num}", size=18, weight=ft.FontWeight.W_700, color=UI["texto"]),
                    ft.Text(str(info_ov.get("cliente") or ""), size=12.5, color=UI["texto_2"]),
                ], spacing=2, tight=True),
                bgcolor=UI["card"],
                content=ft.Container(
                    width=640,
                    content=ft.Column([
                        *aviso_faltante,
                        datos,
                        ft.Container(
                            height=min(420, 60 + 58 * len(filas)),
                            border=ft.Border.all(1, UI["borde"]),
                            border_radius=8,
                            content=ft.Column(filas, spacing=0, scroll=ft.ScrollMode.AUTO),
                        ),
                    ], spacing=12, tight=True),
                ),
                actions=acciones,
            )
            page.show_dialog(dlg_det)
            page.update()

        def exportar_excel_facturacion_netsuite(e=None, solo_ov: dict = None):
            import re
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment

            def normalizar_fecha_vencimiento(valor):
                txt = str(valor or "").strip()
                if not txt or txt.upper() in ("S/F", "SF", "SIN FECHA", "NONE", "NULL", "-"):
                    return "S/F"
                txt = txt.replace(".", "-").replace("/", "-")
                for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d-%m-%y", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        return datetime.strptime(txt[:19], fmt).strftime("%d-%m-%Y")
                    except Exception:
                        pass
                return txt

            def extraer_trazabilidad(texto, lpn_default, unidades_default):
                """Convierte trazabilidad combinada en una fila por LPN/lote/vencimiento."""
                raw = str(texto or "").strip()
                if not raw or raw.upper() in ("NONE", "NULL"):
                    raw = "S/L"
                bloques = [b.strip() for b in re.split(r"\s*\|\s*|\s*;\s*|\n+", raw) if b.strip()]
                salida = []
                for bloque in bloques or ["S/L"]:
                    original = bloque
                    lpn = lpn_default
                    m_lpn = re.search(r"\[([^\]]+)\]", bloque)
                    if m_lpn:
                        lpn = m_lpn.group(1).strip().upper()
                        bloque = (bloque[:m_lpn.start()] + bloque[m_lpn.end():]).strip()
                    unidades = unidades_default
                    m_un = re.search(r"\((\d+(?:[.,]\d+)?)\s*UN\)", bloque, flags=re.I)
                    if m_un:
                        unidades = int(float(m_un.group(1).replace(",", ".")))
                        bloque = (bloque[:m_un.start()] + bloque[m_un.end():]).strip()
                    bloque = re.sub(r"\[Rack:[^\]]*\]", "", bloque, flags=re.I).strip()
                    limpio = re.sub(r"\s+", " ", bloque).strip(" -/")
                    lote, venc = "S/L", "S/F"
                    # S/L es un valor indivisible: nunca se interpreta como lote S y fecha L.
                    if limpio.upper().replace(" ", "") in ("S/L", "SL", "SINLOTE"):
                        lote = "S/L"
                    else:
                        fecha_match = re.search(r"(\d{2}[/-]\d{2}[/-]\d{2,4}|\d{4}[/-]\d{2}[/-]\d{2})", limpio)
                        if fecha_match:
                            venc = normalizar_fecha_vencimiento(fecha_match.group(1))
                            lote_txt = (limpio[:fecha_match.start()] + limpio[fecha_match.end():]).strip(" -/")
                            lote = lote_txt or "S/L"
                        elif re.search(r"\bS\s*/\s*F\b", limpio, flags=re.I):
                            venc = "S/F"
                            lote_txt = re.sub(r"\bS\s*/\s*F\b", "", limpio, flags=re.I).strip(" -/")
                            lote = lote_txt or "S/L"
                        else:
                            lote = limpio or "S/L"
                    salida.append({
                        "LPN_Pallet": lpn or lpn_default,
                        "Lote": lote.upper(),
                        "Fecha_Vencimiento": venc,
                        "Unidades_Lote": unidades,
                        "Trazabilidad_Original": original,
                    })
                # Si solo hay un bloque sin unidades explícitas, usa el total facturable.
                if len(salida) == 1 and salida[0]["Unidades_Lote"] <= 0:
                    salida[0]["Unidades_Lote"] = unidades_default
                return salida

            lista_fact = [solo_ov] if solo_ov else [reg for _, (chk, reg) in checks_facturacion.items() if chk.value]
            if not lista_fact:
                lista_fact = [r for r in registros_packing_db if r.get("estado") == "PENDIENTE_FACTURACION"]
            if not lista_fact:
                notificar("No hay OVs en PENDIENTE_FACTURACION seleccionadas para exportar.", "#D97706")
                return
            try:
                os.makedirs("reportes_facturacion", exist_ok=True)
                ts_now = datetime.now().strftime("%Y%m%d_%H%M%S")
                suf_ov = str(solo_ov.get("ov_base") or solo_ov.get("ov") or "").strip() if solo_ov else "LOTE"
                ruta_xlsx = os.path.join("reportes_facturacion", f"NetSuite_Facturacion_{suf_ov}_{ts_now}.xlsx")
                filas_detalle_ns, filas_resumen_ov = [], []
                filas_resumen_lpn, filas_checklist_recepcion = [], []
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
                    pallets_detalle = ov_item.get("pallets_detalle") or {}
                    lineas = []
                    if pallets_detalle:
                        for lpn_pallet, items_pallet in pallets_detalle.items():
                            for item_pallet in items_pallet:
                                linea_pallet = dict(item_pallet)
                                linea_pallet["lpn_pallet"] = lpn_pallet
                                linea_pallet["lotes"] = str(
                                    linea_pallet.get("lotes")
                                    or f"[{lpn_pallet}] {linea_pallet.get('lote') or 'S/L'} / {linea_pallet.get('fecha_vencimiento_cl') or 'S/F'} ({int(linea_pallet.get('unidades_totales') or linea_pallet.get('cantidad_pickeada') or 0)} UN)"
                                )
                                lineas.append(linea_pallet)
                    else:
                        lineas = list(ov_item.get("lineas_detalle") or [])
                    if not lineas and ov_item.get("id") is not None:
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

                    unid_tot_emp = 0
                    for idx_l, lin in enumerate(lineas or [{"sku": "CONSOLIDADO", "descripcion": "ORDEN EMPACADA EN WMS"}], start=1):
                        sol_u = int(lin.get("cantidad_pedida") or lin.get("cantidad") or ov_item.get("unidades") or 0)
                        pick_u = int(lin.get("unidades_totales") or lin.get("cantidad_pickeada") or sol_u or ov_item.get("unidades_pickeadas") or 1)
                        unid_tot_emp += pick_u
                        if lin.get("lpn_pallet"):
                            trazas = [{
                                "LPN_Pallet": str(lin.get("lpn_pallet") or lpn_cod).upper(),
                                "Lote": str(lin.get("lote") or "S/L").upper(),
                                "Fecha_Vencimiento": normalizar_fecha_vencimiento(lin.get("fecha_vencimiento_cl")),
                                "Unidades_Lote": pick_u,
                                "Trazabilidad_Original": str(lin.get("lotes") or ""),
                            }]
                        else:
                            trazas = extraer_trazabilidad(lin.get("lotes") or "S/L", lpn_cod, pick_u)
                        for traza in trazas:
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
                                "LPN_Pallet": traza["LPN_Pallet"],
                                "Lote": traza["Lote"],
                                "Fecha_Vencimiento": traza["Fecha_Vencimiento"],
                                "Cajas": int(lin.get("cajas") or 0),
                                "Displays": int(lin.get("displays") or 0),
                                "Multiplo_Caja": int(lin.get("multiplo_aplicado") or 1),
                                "Unidades_Lote": traza["Unidades_Lote"],
                                "Trazabilidad_Original": traza["Trazabilidad_Original"],
                                "Estado_Facturacion": ov_item.get("estado", "PENDIENTE_FACTURACION"),
                            })

                    for lpn_pallet, items_pallet in pallets_detalle.items():
                        total_un_lpn = sum(int(i.get("unidades_totales") or i.get("cantidad_pickeada") or 0) for i in items_pallet)
                        total_cajas_lpn = sum(int(i.get("cajas") or 0) for i in items_pallet)
                        total_displays_lpn = sum(int(i.get("displays") or 0) for i in items_pallet)
                        skus_lpn = len({str(i.get("sku") or "").upper() for i in items_pallet if i.get("sku")})
                        filas_resumen_lpn.append({
                            "Numero_OT": ov_limpia,
                            "LPN": lpn_pallet,
                            "Cliente_Destino": cli_nom,
                            "Comuna_Destino": comuna_nom,
                            "Cantidad_SKU": skus_lpn,
                            "Total_Cajas": total_cajas_lpn,
                            "Total_Displays": total_displays_lpn,
                            "Total_Unidades": total_un_lpn,
                            "Estado_Despacho": "EN_TRANSITO_CCP" if ov_limpia.startswith("OT-") else ov_item.get("estado", "PENDIENTE_FACTURACION"),
                            "Recepcionado_CCP": "NO",
                            "Fecha_Recepcion_CCP": "",
                            "Usuario_Recepcion_CCP": "",
                            "Observacion_Recepcion": "",
                        })
                        for i in items_pallet:
                            filas_checklist_recepcion.append({
                                "Numero_OT": ov_limpia,
                                "LPN": lpn_pallet,
                                "SKU": i.get("sku"),
                                "Descripcion": i.get("descripcion"),
                                "Lote": i.get("lote") or "S/L",
                                "Fecha_Vencimiento": normalizar_fecha_vencimiento(i.get("fecha_vencimiento_cl")),
                                "Cajas_Despachadas": int(i.get("cajas") or 0),
                                "Displays_Despachados": int(i.get("displays") or 0),
                                "Unidades_Despachadas": int(i.get("unidades_totales") or i.get("cantidad_pickeada") or 0),
                                "Cajas_Recibidas": "",
                                "Displays_Recibidos": "",
                                "Unidades_Recibidas": "",
                                "Conforme": "",
                                "Diferencia": "",
                                "Observacion": "",
                            })

                    filas_resumen_ov.append({
                        "Numero_OV_NetSuite": ov_limpia,
                        "Canal": canal_str,
                        "Fecha_OV": fecha_ov,
                        "Cliente": cli_nom,
                        "Comuna_Despacho": comuna_nom,
                        "Modalidad": tipo_emp,
                        "N_Bultos_Pallets": cant_bultos,
                        "Cantidad_Total_LPN": len(pallets_detalle) if pallets_detalle else 1,
                        "LPN_Despacho": ", ".join(pallets_detalle.keys()) if pallets_detalle else lpn_cod,
                        "Total_Cajas": sum(int(i.get("cajas") or 0) for items in pallets_detalle.values() for i in items),
                        "Total_Displays": sum(int(i.get("displays") or 0) for items in pallets_detalle.values() for i in items),
                        "Total_Unidades_Facturar": unid_tot_emp,
                        "Estado": "EN_TRANSITO_CCP" if ov_limpia.startswith("OT-") else ov_item.get("estado", "PENDIENTE_FACTURACION"),
                    })

                with pd.ExcelWriter(ruta_xlsx, engine="openpyxl") as writer:
                    pd.DataFrame(filas_detalle_ns).to_excel(writer, sheet_name="1_Subida_NetSuite_Lineas", index=False)
                    pd.DataFrame(filas_resumen_ov).to_excel(writer, sheet_name="2_Resumen_OVs_Bultos", index=False)
                    pd.DataFrame(filas_resumen_lpn).to_excel(writer, sheet_name="3_Resumen_LPN", index=False)
                    pd.DataFrame(filas_checklist_recepcion).to_excel(writer, sheet_name="4_Checklist_Recepcion_CCP", index=False)

                wb = openpyxl.load_workbook(ruta_xlsx)
                fill_hdr = PatternFill(fill_type="solid", start_color="1E3A8A", end_color="1E3A8A")
                font_hdr = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                for ws in wb.worksheets:
                    ws.freeze_panes = "A2"
                    ws.auto_filter.ref = ws.dimensions
                    ws.row_dimensions[1].height = 34
                    for cell in ws[1]:
                        cell.fill = fill_hdr
                        cell.font = font_hdr
                        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                    for col in ws.columns:
                        letra = col[0].column_letter
                        max_largo = max(len(str(c.value or "")) for c in col)
                        ws.column_dimensions[letra].width = min(max(max_largo + 2, 11), 38)
                    if ws.title == "1_Subida_NetSuite_Lineas":
                        encabezados = {c.value: c.column for c in ws[1]}
                        col_v = encabezados.get("Fecha_Vencimiento")
                        if col_v:
                            for fila in range(2, ws.max_row + 1):
                                ws.cell(fila, col_v).alignment = Alignment(horizontal="center")
                wb.save(ruta_xlsx)
                descargar_archivo_web(ruta_xlsx, f"Excel Facturación NetSuite ({len(ovs_procesadas_excel)} OVs)")
            except Exception as ex:
                notificar(f"Error exportando Excel de Facturación: {ex}", "#B91C1C")
        def marcar_ovs_como_facturadas(e=None, ov_unica: dict = None):
            objetivos = [ov_unica] if ov_unica else [reg for _, (chk, reg) in checks_facturacion.items() if chk.value]
            if not objetivos:
                notificar("Seleccione al menos una OV para marcarla como FACTURADA.", "#D97706")
                return
            for it in objetivos:
                cambiar_estado_ov_db(it, "FACTURADO")
            notificar(f"{len(objetivos)} OV(s) marcadas como FACTURADAS en NetSuite.", "#047857")
            recargar_datos_supabase()
            renderizar_monitor_cortes_y_tablas()

        def exportar_ov_farmacia_excel_pdf(info_ov: dict = None):
            exportar_excel_facturacion_netsuite(solo_ov=info_ov)

        # =====================================================================
        # ETAPAS Y COMPONENTES VISUALES DEL SEGUIMIENTO
        # =====================================================================
        def etapa_ov(estado: str) -> int:
            """0 picking · 1 packing · 2 en facturación / tránsito · 3 facturada / recibida."""
            est = str(estado or "").upper()
            if est in ("FACTURADO", "DESPACHADO", "CERRADO", "RECIBIDO_CCP", "RECIBIDO_CCP_CON_DIFERENCIAS"):
                return 3
            if est in ("PENDIENTE_FACTURACION", "LISTA_PARA_CARGA", "EN_TRANSITO_CCP", "RECEPCION_CCP_EN_PROCESO"):
                return 2
            if est in ("PENDIENTE_PACKING", "PACKING_EN_PROCESO", "PICKING_COMPLETO"):
                return 1
            return 0

        COLORES_ETAPA = [UI["alerta"], UI["acento"], "#818CF8", UI["exito"]]
        ordenes_resumen = []

        def nombre_etapa(r: dict) -> str:
            et = etapa_ov(r.get("estado"))
            es_ot = str(r.get("ov") or "").upper().startswith("OT-")
            if et == 2:
                if es_ot and str(r.get("estado") or "").upper() == "LISTA_PARA_CARGA":
                    return "Lista para carga (en Santiago)"
                return "En tránsito a CCP" if es_ot else "En facturación"
            if et == 3:
                return "Recibida en CCP" if es_ot else "Facturada"
            if et == 1 and r.get("mesa"):
                return f"En packing · {str(r.get('mesa')).capitalize()}"
            return ("En picking", "En packing")[et]

        def chip(texto: str, color: str, size: float = 11):
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                bgcolor=ft.Colors.with_opacity(0.14, color),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.55, color)),
                border_radius=12,
                content=ft.Text(texto, size=size, weight=ft.FontWeight.W_600, color=color),
            )

        def chip_canal(r: dict):
            ov_u = str(r.get("ov") or "").upper()
            if ov_u.startswith("OT-"):
                return chip("Traslado", "#A78BFA")
            return chip("Farmacia", "#FBBF24") if r.get("es_farmacia") else chip("Normal", UI["texto_2"])

        def pasos_avance(r: dict):
            """Picking → Packing → Facturación: tres segmentos y el nombre de la etapa actual."""
            et = etapa_ov(r.get("estado"))
            segmentos = []
            for i in range(3):
                color = UI["exito"] if i < et or et == 3 else (COLORES_ETAPA[et] if i == et else "#3B484B")
                segmentos.append(ft.Container(width=26, height=6, border_radius=3, bgcolor=color))
            return ft.Row(
                [ft.Row(segmentos, spacing=3, tight=True),
                 ft.Text(nombre_etapa(r), size=12, weight=ft.FontWeight.W_600, color=COLORES_ETAPA[et])],
                spacing=10, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        def menu_fila(items: list):
            """Acciones de una fila en un solo botón ⋮ (evita varios botones por fila)."""
            return ft.PopupMenuButton(
                icon=ft.Icons.MORE_VERT_ROUNDED,
                icon_color=UI["texto_2"],
                tooltip="Acciones",
                items=[
                    ft.PopupMenuItem(
                        content=ft.Row([ft.Icon(ico, size=18, color=UI["acento"]), ft.Text(txt, size=12)], spacing=10),
                        on_click=fn,
                    )
                    for txt, ico, fn in items
                ],
            )

        def altura_tabla(reservado: int) -> int:
            """Las tablas usan el alto real de la ventana (antes quedaban fijas en 390 px)."""
            try:
                return max(320, int(float(page.height or 800) - reservado))
            except Exception:
                return 420

        def cumple_filtros_comunes(r: dict) -> bool:
            if filtro_dia_ov_activo != "TODOS" and str(r.get("fecha_ov") or "")[:10] != filtro_dia_ov_activo:
                return False
            if filtro_canal_ov_activo == "NORMAL" and r.get("es_farmacia"):
                return False
            if filtro_canal_ov_activo == "FARMACIA" and not r.get("es_farmacia"):
                return False
            return True

        def renderizar_monitor_cortes_y_tablas():
            # ---------- 1. Resumen: KPI y avance por corte ----------
            base_resumen = [r for r in registros_packing_db if cumple_filtros_comunes(r)]
            ordenes_resumen[:] = base_resumen
            por_etapa = [0, 0, 0, 0]
            for r in base_resumen:
                por_etapa[etapa_ov(r.get("estado"))] += 1
            n_fa = sum(1 for r in base_resumen if r.get("es_farmacia"))
            lbl_kpi_total_ovs.value = str(len(base_resumen))
            lbl_det_total.value = f"{len(base_resumen) - n_fa} normales · {n_fa} farmacia"
            lbl_kpi_picking.value = str(por_etapa[0])
            lbl_kpi_packing.value = str(por_etapa[1])
            lbl_kpi_fact.value = str(por_etapa[2] + por_etapa[3])
            lbl_det_fact.value = f"{por_etapa[3]} ya facturadas / recibidas"
            renderizar_mesas(base_resumen)
            con_faltante = [r for r in base_resumen if r.get("faltante")]
            alerta_faltantes.visible = bool(con_faltante)
            lbl_alerta_faltantes.value = f"{len(con_faltante)} orden(es) salieron con faltante"
            fila_chips_faltantes.controls = [
                ft.Container(
                    content=chip(f"{r['ov']} · {r.get('faltante')} UN", UI["peligro"], 11.5),
                    on_click=lambda e, it=r: mostrar_modal_detalle_ov(it["ov"], it),
                    tooltip=f"{r.get('cliente', '')} · {r.get('motivo_faltante') or ''}",
                    ink=True, border_radius=12,
                ) for r in con_faltante
            ]

            cortes_orden = ["09:00", "10:00", "12:00", "13:00", ">13:00"]
            agrupado = {c: [] for c in cortes_orden}
            for r in base_resumen:
                agrupado[r.get("corte") if r.get("corte") in agrupado else ">13:00"].append(r)

            col_cortes_resumen.controls.clear()
            for c in cortes_orden:
                lista_c = agrupado[c]
                n = len(lista_c)
                cuenta = [0, 0, 0, 0]
                for r in lista_c:
                    cuenta[etapa_ov(r.get("estado"))] += 1
                listas = cuenta[2] + cuenta[3]
                pct = int(round(100 * listas / n)) if n else 0
                barra = ft.Row(
                    [ft.Container(expand=cuenta[i], height=10, bgcolor=COLORES_ETAPA[i]) for i in range(4) if cuenta[i] > 0]
                    or [ft.Container(expand=1, height=10, bgcolor="#2B3537")],
                    spacing=2, expand=True,
                )
                chips = [
                    ft.Container(
                        content=chip(r["ov"], COLORES_ETAPA[etapa_ov(r.get("estado"))], 11.5),
                        on_click=lambda e, it=r: mostrar_modal_detalle_ov(it["ov"], it),
                        tooltip=f"{r.get('cliente', '')} · {nombre_etapa(r)}",
                        ink=True, border_radius=12,
                    )
                    for r in lista_c[:40]
                ]
                if n > 40:
                    chips.append(ft.Text(f"+{n - 40} más", size=11, color=UI["texto_2"]))
                activo = filtro_corte_activo == c
                col_cortes_resumen.controls.append(ft.Container(
                    padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                    border_radius=8,
                    bgcolor=UI["card_alt"],
                    border=ft.Border.all(1, UI["acento"] if activo else UI["borde"]),
                    content=ft.Column([
                        ft.Row([
                            ft.Text(f"Corte {c}", size=13, weight=ft.FontWeight.W_700, color=UI["texto"], width=96),
                            ft.Text(f"{n} OV", size=13, weight=ft.FontWeight.W_600, color=UI["texto_2"], width=56),
                            ft.Container(content=barra, expand=True, border_radius=5, clip_behavior=ft.ClipBehavior.HARD_EDGE),
                            ft.Text(f"{pct}% lista" if n else "—", size=12, weight=ft.FontWeight.W_600,
                                    color=UI["exito"] if n and pct == 100 else UI["texto_2"], width=74,
                                    text_align=ft.TextAlign.RIGHT),
                            ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT_ROUNDED, icon_color=UI["acento"], icon_size=20,
                                          tooltip=f"Ver las OV del corte {c} en Seguimiento",
                                          on_click=lambda e, cc=c: ir_a_seguimiento_corte(cc), disabled=n == 0),
                        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        *([ft.Row(chips, wrap=True, spacing=6, run_spacing=6)] if chips else []),
                    ], spacing=8, tight=True),
                ))

            # ---------- 2. Seguimiento ----------
            q_busq = (txt_buscar_ov_unificada.value or "").strip().upper()
            etapa_sel = dd_filtro_etapa.value or "TODAS"
            filtradas = []
            for r in registros_packing_db:
                if not cumple_filtros_comunes(r):
                    continue
                if filtro_corte_activo != "TODOS" and r.get("corte") != filtro_corte_activo:
                    continue
                if etapa_sel != "TODAS" and str(etapa_ov(r.get("estado"))) != etapa_sel:
                    continue
                if q_busq and not any(q_busq in str(r.get(k, "")).upper() for k in ("ov", "cliente", "comuna", "fecha_ov", "lpn")):
                    continue
                filtradas.append(r)
            lbl_conteo_seguimiento.value = f"{len(filtradas)} orden(es)"

            filas = []
            for r in filtradas:
                ped = int(r.get("unidades") or 0)
                pick = int(r.get("unidades_pickeadas") or 0)
                et = etapa_ov(r.get("estado"))
                bultos_txt = f"{r.get('bultos', 1)} {str(r.get('tipo_empaque') or 'BULTO').lower()}" if et >= 2 else "—"
                filas.append(ft.DataRow(
                    on_select_change=lambda e, it=r: mostrar_modal_detalle_ov(it["ov"], it),
                    cells=[
                        ft.DataCell(ft.Text(r["ov"], size=13, weight=ft.FontWeight.W_700, color=UI["texto"])),
                        ft.DataCell(chip_canal(r)),
                        ft.DataCell(ft.Text(f"{r.get('fecha_ov', '-')}  ·  {r.get('corte', '-')}", size=12, color=UI["texto_2"])),
                        ft.DataCell(ft.Text(str(r.get("cliente") or "-")[:44], size=12.5, color=UI["texto"], tooltip=str(r.get("cliente") or ""))),
                        ft.DataCell(ft.Text(f"{pick} / {ped} UN", size=12.5, weight=ft.FontWeight.W_600,
                                            color=UI["exito"] if ped and pick >= ped else (UI["alerta"] if pick else UI["texto_2"]))),
                        ft.DataCell(ft.Row([
                            pasos_avance(r),
                            *([chip(f"Faltante {r.get('faltante')} UN", UI["peligro"])] if r.get("faltante") else []),
                        ], spacing=8, tight=True)),
                        ft.DataCell(ft.Text(bultos_txt, size=12, color=UI["texto_2"])),
                        ft.DataCell(menu_fila([
                            ("Ver detalle de SKU y lotes", ft.Icons.LIST_ALT_ROUNDED, lambda e, it=r: mostrar_modal_detalle_ov(it["ov"], it)),
                            ("Imprimir etiquetas de bultos", ft.Icons.QR_CODE_2_ROUNDED, lambda e, it=r: imprimir_etiqueta_packing_bultos_ov(it)),
                            ("Packing list (Excel)", ft.Icons.TABLE_VIEW_ROUNDED, lambda e, it=r: exportar_ov_farmacia_excel_pdf(it)),
                        ])),
                    ],
                ))
            tabla_listado_unico_ovs.rows = filas
            txt_vacio_seguimiento.visible = not filas
            cont_tabla_listado_unico.height = altura_tabla(250)

            # ---------- 3. Facturación ----------
            q_fact = (txt_buscar_facturacion.value or "").strip().upper()
            checks_facturacion.clear()
            filtradas_fact, vistas = [], set()
            for r in registros_packing_db:
                est = r.get("estado")
                if not (est == "PENDIENTE_FACTURACION" or (sw_ver_ya_facturadas.value and est == "FACTURADO")):
                    continue
                clave = str(r.get("ov_base") or r.get("ov") or "").strip().upper().removesuffix("-FA").strip()
                if not clave or clave in vistas:
                    continue
                if q_fact and not any(q_fact in str(r.get(k, "")).upper() for k in ("ov", "cliente", "comuna", "lpn", "tipo_empaque")):
                    continue
                vistas.add(clave)
                filtradas_fact.append(r)

            filas_f = []
            for r in filtradas_fact:
                est = r.get("estado", "PENDIENTE_FACTURACION")
                chk = ft.Checkbox(value=(est == "PENDIENTE_FACTURACION"), active_color=UI["acento"],
                                  on_change=lambda e: actualizar_resumen_facturacion())
                checks_facturacion[r["ov"]] = (chk, r)
                filas_f.append(ft.DataRow(cells=[
                    ft.DataCell(chk),
                    ft.DataCell(ft.Text(r["ov"], size=13, weight=ft.FontWeight.W_700, color=UI["texto"])),
                    ft.DataCell(chip_canal(r)),
                    ft.DataCell(ft.Text(str(r.get("fecha_ov") or "-"), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(str(r.get("cliente") or "-")[:40], size=12.5, color=UI["texto"], tooltip=str(r.get("cliente") or ""))),
                    ft.DataCell(ft.Text(str(r.get("comuna") or "SANTIAGO"), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(f"{r.get('bultos', 1)} {str(r.get('tipo_empaque') or 'BULTO').lower()}", size=12.5, color=UI["texto"])),
                    ft.DataCell(ft.Text(f"{int(r.get('unidades_pickeadas') or r.get('unidades') or 0)} UN", size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"])),
                    ft.DataCell(ft.Row([
                        chip("Facturada", UI["exito"]) if est == "FACTURADO" else chip("Por facturar", "#818CF8"),
                        *([chip(f"Faltante {r.get('faltante')} UN", UI["peligro"])] if r.get("faltante") else []),
                    ], spacing=6, tight=True)),
                    ft.DataCell(menu_fila([
                        ("Excel NetSuite de esta OV", ft.Icons.TABLE_VIEW_ROUNDED, lambda e, it=r: exportar_excel_facturacion_netsuite(solo_ov=it)),
                        ("Etiquetas de bultos", ft.Icons.QR_CODE_2_ROUNDED, lambda e, it=r: imprimir_etiqueta_packing_bultos_ov(it)),
                        ("PDF contenido de pallets", ft.Icons.PICTURE_AS_PDF_ROUNDED, lambda e, it=r: descargar_pdf_contenido_pallets(it)),
                        ("Marcar como facturada", ft.Icons.DONE_ALL_ROUNDED, lambda e, it=r: marcar_ovs_como_facturadas(ov_unica=it)),
                    ])),
                ]))
            tabla_facturacion_ns.rows = filas_f
            txt_vacio_facturacion.visible = not filas_f
            cont_tabla_facturacion.height = altura_tabla(250)
            actualizar_resumen_facturacion(actualizar=False)
            page.update()

        def actualizar_resumen_facturacion(actualizar: bool = True):
            total = len(checks_facturacion)
            sel = sum(1 for chk, _ in checks_facturacion.values() if chk.value)
            lbl_resumen_facturacion.value = f"{total} orden(es) empacadas · {sel} seleccionada(s) para el Excel de NetSuite"
            btn_marcar_facturadas.disabled = sel == 0
            if actualizar:
                page.update()

        def ir_a_seguimiento_corte(corte_sel: str):
            nonlocal filtro_corte_activo
            filtro_corte_activo = corte_sel
            dd_filtro_corte.value = corte_sel
            self.sel_sub_olas(2)

        def aplicar_filtro_corte_rapido(corte_sel: str):
            cambiar_filtro_estado_interno(corte_sel)
            renderizar_monitor_cortes_y_tablas()

        def cambiar_filtro_corte_dropdown(e=None):
            nonlocal filtro_corte_activo
            filtro_corte_activo = dd_filtro_corte.value or "TODOS"
            renderizar_monitor_cortes_y_tablas()

        def cambiar_filtro_canal_dropdown(e=None):
            nonlocal filtro_canal_ov_activo
            filtro_canal_ov_activo = dd_filtro_canal_ov.value or "TODOS"
            renderizar_monitor_cortes_y_tablas()

        dd_filtro_corte.on_select = cambiar_filtro_corte_dropdown
        dd_filtro_canal_ov.on_select = cambiar_filtro_canal_dropdown
        dd_filtro_etapa.on_select = lambda e: renderizar_monitor_cortes_y_tablas()
        txt_buscar_ov_unificada.on_change = lambda e: renderizar_monitor_cortes_y_tablas()
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

        def actualizar_resumen_prev():
            total = len(olas_extraidas_ns)
            sel = sum(1 for it in olas_extraidas_ns if it.get("seleccionada", True))
            lbl_resumen_prev.value = f"{total} orden(es) · {sel} seleccionada(s)" if total else "Sin órdenes extraídas"

        def cambiar_check_individual(e, item_ola: dict):
            item_ola["seleccionada"] = bool(e.control.value)
            actualizar_resumen_prev()
            page.update()

        def renderizar_tabla_previsualizacion():
            checks_liberacion.clear()
            filas = []
            for item in olas_extraidas_ns:
                ov_cod = item["ov"]
                chk = ft.Checkbox(value=item.get("seleccionada", True), active_color=UI["acento"],
                                  on_change=lambda e, it=item: cambiar_check_individual(e, it))
                checks_liberacion[ov_cod] = chk
                es_fa = item.get("es_farmacia", False)
                filas.append(ft.DataRow(cells=[
                    ft.DataCell(chk),
                    ft.DataCell(ft.Text(ov_cod, size=13, weight=ft.FontWeight.W_700, color=UI["texto"])),
                    ft.DataCell(ft.Text(str(item.get("fecha_ov") or "-"), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(f"{item.get('corte', '09:00')} hrs", size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Container(
                        content=chip("Farmacia (-FA)", "#FBBF24") if es_fa else chip("Normal", UI["texto_2"]),
                        on_click=lambda e, it=item: alternar_canal_farmacia_manual(it),
                        tooltip="Cambiar entre Normal y Farmacia", ink=True, border_radius=12,
                    )),
                    ft.DataCell(ft.Text(str(item.get("cliente") or "-")[:44], size=12.5, color=UI["texto"])),
                    ft.DataCell(ft.Text(str(item.get("lineas_cnt", 1)), size=12.5, color=UI["texto"])),
                    ft.DataCell(ft.Text(f"{item.get('unidades', 0)} UN", size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"])),
                    ft.DataCell(ft.IconButton(icon=ft.Icons.LIST_ALT_ROUNDED, icon_size=18, icon_color=UI["acento"], tooltip="Ver SKU",
                                              on_click=lambda ev, cod=ov_cod, inf=item: mostrar_modal_detalle_ov(cod, inf))),
                ]))
            tabla_previsualizacion_ns.rows = filas
            txt_vacio_prev.visible = not filas
            cont_tabla_prev_ns.visible = bool(filas)
            cont_tabla_prev_ns.height = altura_tabla(330)
            actualizar_resumen_prev()
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
                filas_maestra = leer_tabla_paginada(lambda: supabase.table("maestra_sku").select("*"))
                for row in filas_maestra:
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
                        ABS(tl.quantity) AS cantidad,
                        tl.quantity AS cantidad_raw
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

                # Las órdenes de traslado (TrnfrOrd) traen cada ítem en varias líneas internas
                # (salida / tránsito / recepción). Con ABS(quantity) las cantidades se triplicaban.
                filas_antes = len(df_ov)
                df_ov = depurar_lineas_traslado(df_ov)
                lineas_depuradas = filas_antes - len(df_ov)

                agrupado_olas = {}
                corte_forzado_ui = None if dd_corte_asignar.value == "AUTO" else dd_corte_asignar.value
                for _, fila in df_ov.iterrows():
                    cant_item = int(float(fila.get("cantidad") or 0))
                    ov_raw = str(fila.get("numero_ov") or "").strip()
                    sku_str = str(fila.get("sku") or "").strip().upper()
                    if cant_item <= 0 or not ov_raw or not sku_str or sku_str in ("NONE", "NULL"):
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
                            "ov_base": ov_base,
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
                    agrupado_olas[ov_clave]["lineas_detalle"].append({"sku": sku_str, "descripcion": desc_str, "cantidad": cant_item, "es_farmacia": es_linea_fa})

                olas_extraidas_ns = list(agrupado_olas.values())
                cant_fa = sum(1 for x in olas_extraidas_ns if x.get("es_farmacia"))
                txt_estado_erp.value = f"Extracción exitosa: {len(olas_extraidas_ns)} Olas ({len(olas_extraidas_ns) - cant_fa} Estándar | {cant_fa} Farmacia -FA)."
                if lineas_depuradas:
                    txt_estado_erp.value += f" Se descartaron {lineas_depuradas} líneas internas repetidas de traslados."
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

            liberadas_ok = 0
            omitidas_con_avance = []
            ovs_liberadas_set = set()
            bodega_act = obtener_bodega_activa(self.page)

            for item in seleccionadas:
                es_fa = bool(item.get("es_farmacia"))
                ov_final = str(item["ov"]).strip()
                if es_fa and not ov_final.upper().endswith("-FA") and not ov_final.upper().startswith("OT-"):
                    ov_final = f"{ov_final}-FA"
                ov_sin_fa = ov_final.removesuffix("-FA").strip()
                cli_nom = str(item.get("cliente") or "CLIENTE REGISTRADO").strip()
                canal_str = "FARMACIA (-FA)" if es_fa else "ESTANDAR"
                id_ext_str = str(item.get("id_externo_ns") or item.get("ov_original") or ov_final).strip()

                # Generar olas ya NO asigna operador: la OV queda sin asignar hasta que el supervisor
                # presione "Cargar OV a los equipos" en Monitor de usuarios (por equipo Farmacia / Picking).
                operador_elegido = None

                payload_ov = {
                    "bodega": bodega_act,
                    "id_externo_ns": id_ext_str,
                    "numero_ov": ov_final,
                    "cliente_nombre": cli_nom,
                    "canal_venta": canal_str,
                    "fecha_emision_ns": datetime.now().isoformat(),
                    "estado_ns": "PENDIENTE_PICKING",
                    "operador_asignado": operador_elegido,
                }

                id_ov_db = None
                try:
                    r_exist = supabase.table("netsuite_ordenes_venta").select("id, estado_ns").or_(f"numero_ov.eq.{ov_final},numero_ov.eq.{ov_sin_fa}").limit(1).execute()
                    if r_exist.data:
                        id_ov_db = r_exist.data[0].get("id")
                        # Una OV con avance NO se vuelve a liberar: antes se borraban sus líneas
                        # (perdiendo lo pickeado) y volvía a PENDIENTE_PICKING aunque estuviera en packing.
                        estado_prev = str(r_exist.data[0].get("estado_ns") or "").strip().upper()
                        r_avance = supabase.table("netsuite_detalle_ov").select("id").eq("orden_id", id_ov_db).gt("cantidad_pickeada", 0).limit(1).execute()
                        if r_avance.data or estado_prev not in ("", "PENDIENTE", "PENDIENTE_PICKING"):
                            omitidas_con_avance.append(f"{ov_final} ({estado_prev or 'CON PICKING'})")
                            continue
                        supabase.table("netsuite_ordenes_venta").update(payload_ov).eq("id", id_ov_db).execute()
                    else:
                        r_ins = supabase.table("netsuite_ordenes_venta").insert(payload_ov).execute()
                        if r_ins.data:
                            id_ov_db = r_ins.data[0].get("id")
                except Exception:
                    try:
                        copia_sb = dict(payload_ov)
                        copia_sb.pop("bodega", None)
                        copia_sb.pop("operador_asignado", None)
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
            notificar(f"¡{liberadas_ok} OVs liberadas y asignadas automáticamente a operadores RF!", "#047857")
            if omitidas_con_avance:
                notificar(
                    f"No se re-liberaron {len(omitidas_con_avance)} OV con avance (para no perder lo pickeado): "
                    + ", ".join(omitidas_con_avance[:8]),
                    "#D97706",
                )
            renderizar_tabla_previsualizacion()
            cargar_monitor_packing_dual()

        # =====================================================================
        # PANTALLAS (una tarea por pantalla, una acción principal por pantalla)
        # =====================================================================
        def vacio(texto: str):
            return ft.Container(
                visible=False, padding=30, alignment=ft.Alignment.CENTER,
                content=ft.Column([
                    ft.Icon(ft.Icons.INBOX_OUTLINED, size=36, color=UI["texto_3"]),
                    ft.Text(texto, size=13, color=UI["texto_2"], text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6, tight=True),
            )

        txt_vacio_seguimiento = vacio("No hay órdenes con estos filtros.")
        txt_vacio_facturacion = vacio("No hay órdenes empacadas pendientes de facturar.")
        txt_vacio_prev = vacio("Extraiga órdenes desde NetSuite o suba el Excel de traslado para verlas aquí.")
        txt_vacio_prev.visible = True

        # ---------- 1. RESUMEN ----------
        def mostrar_lista_kpi(titulo: str, etapas: tuple):
            """Al tocar un indicador: lista de OV con su cliente; cada fila abre el detalle."""
            lista = [r for r in ordenes_resumen if etapas is None or etapa_ov(r.get("estado")) in etapas]
            lista.sort(key=lambda r: (str(r.get("corte") or ""), str(r.get("ov") or "")))

            def cerrar(ev=None):
                try:
                    page.pop_dialog()
                except Exception:
                    dlg.open = False
                page.update()

            def abrir(r):
                cerrar()
                mostrar_modal_detalle_ov(r["ov"], r)

            filas = [
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                    border=ft.Border(bottom=ft.BorderSide(0.5, UI["borde"])),
                    ink=True,
                    on_click=lambda e, it=r: abrir(it),
                    content=ft.Row([
                        ft.Column([
                            ft.Text(r["ov"], size=13.5, weight=ft.FontWeight.W_700, color=UI["texto"]),
                            ft.Text(str(r.get("cliente") or "-"), size=12, color=UI["texto_2"], max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                        ], spacing=1, tight=True, expand=True),
                        chip_canal(r),
                        ft.Text(f"{r.get('fecha_ov', '-')} · {r.get('corte', '-')}", size=11.5, color=UI["texto_3"], width=130),
                        chip(nombre_etapa(r), COLORES_ETAPA[etapa_ov(r.get("estado"))]),
                    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                )
                for r in lista
            ] or [ft.Container(padding=20, content=ft.Text("No hay órdenes en este grupo.", size=12.5, color=UI["texto_2"]))]

            dlg = ft.AlertDialog(
                title=ft.Column([
                    ft.Text(titulo, size=18, weight=ft.FontWeight.W_700, color=UI["texto"]),
                    ft.Text(f"{len(lista)} orden(es) · toque una para ver sus SKU", size=12, color=UI["texto_2"]),
                ], spacing=2, tight=True),
                bgcolor=UI["card"],
                content=ft.Container(
                    width=720,
                    height=min(480, 70 + 62 * len(filas)),
                    border=ft.Border.all(1, UI["borde"]),
                    border_radius=8,
                    content=ft.Column(filas, spacing=0, scroll=ft.ScrollMode.AUTO),
                ),
                actions=[ui_boton("Cerrar", None, cerrar, "texto")],
            )
            page.show_dialog(dlg)
            page.update()

        fila_chips_faltantes = ft.Row(spacing=6, wrap=True, run_spacing=6)
        lbl_alerta_faltantes = ft.Text("", size=13, weight=ft.FontWeight.W_700, color="#FCA5A5")
        alerta_faltantes = ft.Container(
            visible=False, padding=14, border_radius=10,
            bgcolor=ft.Colors.with_opacity(0.10, UI["peligro"]), border=ft.Border.all(1, UI["peligro"]),
            content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.REPORT_PROBLEM_OUTLINED, color=UI["peligro"], size=20), lbl_alerta_faltantes], spacing=8),
                ft.Text("Revise el stock de esos SKU (quedaron como FALTANTE_PACKING en el kardex). Toque una OV para ver el motivo.",
                        size=11.5, color=UI["texto_2"]),
                fila_chips_faltantes,
            ], spacing=8, tight=True),
        )

        CANTIDAD_MESAS = 6
        fila_mesas = ft.ResponsiveRow(spacing=12, run_spacing=12)

        def renderizar_mesas(base: list):
            en_mesa = {}
            for r in base:
                if etapa_ov(r.get("estado")) == 1 and r.get("mesa"):
                    en_mesa.setdefault(r["mesa"], []).append(r)
            nombres = [f"MESA {i}" for i in range(1, CANTIDAD_MESAS + 1)]
            nombres += sorted(m for m in en_mesa if m not in nombres)
            sin_mesa = [r for r in base if etapa_ov(r.get("estado")) == 1 and not r.get("mesa")]
            tiles = []
            for m in nombres:
                ovs = en_mesa.get(m, [])
                tiles.append(ft.Container(
                    col={"xs": 6, "md": 4, "lg": 2},
                    padding=12, border_radius=10,
                    bgcolor=UI["card_alt"],
                    border=ft.Border.all(1, UI["acento"] if ovs else UI["borde"]),
                    content=ft.Column([
                        ft.Row([
                            ft.Text(m.capitalize(), size=14, weight=ft.FontWeight.W_700, color=UI["texto"]),
                            chip(f"{len(ovs)} OV" if ovs else "Libre", UI["acento"] if ovs else UI["texto_3"], 10.5),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        *[ft.Container(
                            ink=True, border_radius=6, padding=ft.Padding.symmetric(horizontal=4, vertical=3),
                            on_click=lambda e, it=r: mostrar_modal_detalle_ov(it["ov"], it),
                            content=ft.Column([
                                ft.Text(r["ov"], size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"]),
                                ft.Text(str(r.get("cliente") or "-"), size=11, color=UI["texto_2"], max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                            ], spacing=0, tight=True),
                        ) for r in ovs],
                    ], spacing=6, tight=True),
                ))
            if sin_mesa:
                tiles.append(ft.Container(
                    col={"xs": 12, "md": 8, "lg": 4},
                    padding=12, border_radius=10, bgcolor=UI["card_alt"], border=ft.Border.all(1, UI["alerta"]),
                    content=ft.Column([
                        ft.Text(f"{len(sin_mesa)} pickeada(s) sin mesa registrada", size=13, weight=ft.FontWeight.W_700, color=UI["alerta"]),
                        ft.Row([ft.Container(content=chip(r["ov"], UI["alerta"], 11), ink=True, border_radius=12,
                                             on_click=lambda e, it=r: mostrar_modal_detalle_ov(it["ov"], it)) for r in sin_mesa],
                               wrap=True, spacing=6, run_spacing=6),
                    ], spacing=6, tight=True),
                ))
            fila_mesas.controls = tiles

        tarjeta_mesas = ui_tarjeta(
            fila_mesas,
            titulo="Mesas de packing",
            subtitulo="Pedidos pickeados esperando en cada mesa. Toque una OV para ver su detalle o cambiarla de mesa.",
            icono=ft.Icons.TABLE_RESTAURANT_ROUNDED,
        )

        fila_kpis_resumen = ft.ResponsiveRow([
            ui_kpi(lbl_kpi_total_ovs, "Órdenes del período", ft.Icons.RECEIPT_LONG_OUTLINED, UI["texto_2"], lbl_det_total),
            ui_kpi(lbl_kpi_picking, "En picking", ft.Icons.SHOPPING_CART_OUTLINED, UI["alerta"],
                   ft.Text("Liberadas a RF, sin cerrar", size=11, color=UI["texto_3"])),
            ui_kpi(lbl_kpi_packing, "En packing", ft.Icons.INVENTORY_2_OUTLINED, UI["acento"],
                   ft.Text("Pickeadas, por empacar", size=11, color=UI["texto_3"])),
            ui_kpi(lbl_kpi_fact, "Enviadas a facturación", ft.Icons.TASK_ALT_ROUNDED, UI["exito"], lbl_det_fact),
        ], spacing=12, run_spacing=12)
        # Indicadores clicables: muestran las OV del grupo con su cliente
        for kpi_ctrl, (titulo_kpi, etapas_kpi) in zip(fila_kpis_resumen.controls, [
            ("Órdenes del período", None),
            ("En picking", (0,)),
            ("En packing", (1,)),
            ("Enviadas a facturación", (2, 3)),
        ]):
            kpi_ctrl.ink = True
            kpi_ctrl.tooltip = "Ver las órdenes"
            kpi_ctrl.on_click = lambda e, t=titulo_kpi, et=etapas_kpi: mostrar_lista_kpi(t, et)

        leyenda_etapas = ft.Row([
            ft.Row([ft.Container(width=10, height=10, border_radius=2, bgcolor=COLORES_ETAPA[i]),
                    ft.Text(t, size=11, color=UI["texto_2"])], spacing=5, tight=True)
            for i, t in enumerate(["Picking", "Packing", "Facturación / tránsito", "Facturada"])
        ], spacing=14, wrap=True)

        tarjeta_cortes = ui_tarjeta(
            col_cortes_resumen,
            titulo="Avance por corte horario",
            subtitulo="Toque una OV para ver su detalle, o la flecha para abrir el corte en Seguimiento.",
            icono=ft.Icons.SCHEDULE_ROUNDED,
            acciones=[leyenda_etapas],
        )
        subvista_resumen = ft.Column([alerta_faltantes, fila_kpis_resumen, tarjeta_mesas, tarjeta_cortes], spacing=12)

        # ---------- 2. CREAR / LIBERAR OLAS ----------
        tarjeta_origen = ui_tarjeta(
            ft.Column([
                ft.Row([
                    txt_fecha_desde, txt_fecha_hasta, dd_corte_asignar,
                    ui_boton("Extraer de NetSuite", ft.Icons.CLOUD_DOWNLOAD_OUTLINED, extraer_ordenes_netsuite),
                    ui_boton("Subir Excel traslado SCL → CCP", ft.Icons.UPLOAD_FILE_ROUNDED, abrir_selector_traslado, "secundario"),
                ], spacing=10, wrap=True, run_spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                txt_estado_erp,
            ], spacing=8, tight=True),
            titulo="1. Origen de las órdenes",
            icono=ft.Icons.INPUT_ROUNDED,
        )
        tarjeta_extraccion_netsuite = ui_tarjeta(
            ft.Column([cont_tabla_prev_ns, txt_vacio_prev], spacing=0, tight=True),
            titulo="2. Revisar y liberar a picking RF",
            subtitulo=None,
            icono=ft.Icons.PLAYLIST_ADD_CHECK_ROUNDED,
            acciones=[
                lbl_resumen_prev,
                ui_menu("Selección", ft.Icons.CHECKLIST_ROUNDED, [
                    ("Marcar todas", ft.Icons.CHECK_BOX_OUTLINED, marcar_todas_olas),
                    ("Solo farmacia (-FA)", ft.Icons.MEDICAL_SERVICES_OUTLINED, marcar_solo_farmacia_olas),
                    ("Desmarcar todas", ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED, desmarcar_todas_olas),
                ]),
                ui_boton("Liberar a picking RF", ft.Icons.SEND_ROUNDED, liberar_olas_a_terminal_rf),
            ],
        )
        subvista_extraccion = ft.Column([tarjeta_origen, tarjeta_extraccion_netsuite], spacing=12)

        # ---------- 3. SEGUIMIENTO ----------
        txt_buscar_ov_unificada.width = None
        txt_buscar_ov_unificada.expand = True
        txt_buscar_ov_unificada.prefix_icon = ft.Icons.SEARCH_ROUNDED
        barra_filtros_seguimiento = ft.ResponsiveRow([
            ft.Container(content=txt_buscar_ov_unificada, col={"xs": 12, "md": 12, "lg": 4}),
            ft.Container(content=dd_filtro_corte, col={"xs": 6, "md": 3, "lg": 2}),
            ft.Container(content=dd_filtro_canal_ov, col={"xs": 6, "md": 3, "lg": 2}),
            ft.Container(content=dd_filtro_etapa, col={"xs": 6, "md": 3, "lg": 2}),
            ft.Container(content=ft.Row([btn_abrir_calendario_ov, btn_limpiar_dia], spacing=4, tight=True), col={"xs": 6, "md": 3, "lg": 2}),
        ], spacing=10, run_spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        tarjeta_listado_unico_ovs = ui_tarjeta(
            ft.Column([barra_filtros_seguimiento, cont_tabla_listado_unico, txt_vacio_seguimiento], spacing=12, tight=True),
            titulo="Órdenes de venta y traslados",
            icono=ft.Icons.FACT_CHECK_OUTLINED,
            acciones=[lbl_conteo_seguimiento],
        )
        subvista_seguimiento = ft.Column([tarjeta_listado_unico_ovs], spacing=12)

        # ---------- 4. FACTURACIÓN ----------
        txt_buscar_facturacion.prefix_icon = ft.Icons.SEARCH_ROUNDED
        btn_marcar_facturadas = ui_boton("Marcar como facturadas", ft.Icons.DONE_ALL_ROUNDED, marcar_ovs_como_facturadas, "secundario")
        tarjeta_modulo_facturacion = ui_tarjeta(
            ft.Column([
                ft.Row([txt_buscar_facturacion, sw_ver_ya_facturadas], spacing=14, wrap=True,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                cont_tabla_facturacion,
                txt_vacio_facturacion,
            ], spacing=12, tight=True),
            titulo="Órdenes empacadas",
            subtitulo=None,
            icono=ft.Icons.RECEIPT_LONG_ROUNDED,
            acciones=[
                lbl_resumen_facturacion,
                btn_marcar_facturadas,
                ui_boton("Descargar Excel NetSuite", ft.Icons.CLOUD_UPLOAD_OUTLINED, exportar_excel_facturacion_netsuite),
            ],
        )
        subvista_facturacion = ft.Column([tarjeta_modulo_facturacion], spacing=12)

        # ---------- Encabezado común ----------
        titulo_pagina = ft.Text("Resumen operativo", size=18, weight=ft.FontWeight.W_700, color=UI["texto"])
        subtitulo_pagina = ft.Text("", size=12, color=UI["texto_2"])
        acciones_pagina = ft.Row([], spacing=8, wrap=True, run_spacing=8)
        barra_proceso = ft.Row(
            [
                ft.Row([ft.Icon(ft.Icons.MOVE_TO_INBOX_OUTLINED, size=24, color=UI["acento"]),
                        ft.Column([titulo_pagina, subtitulo_pagina], spacing=1, tight=True)],
                       spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                acciones_pagina,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True, run_spacing=10,
        )
        btn_actualizar = ui_boton("Actualizar", ft.Icons.SYNC_ROUNDED, cargar_monitor_packing_dual, "secundario")
        menu_exportar_seguimiento = ui_menu("Exportar", ft.Icons.DOWNLOAD_ROUNDED, [
            ("Packing list de las OV (Excel)", ft.Icons.TABLE_VIEW_ROUNDED, lambda e: exportar_ov_farmacia_excel_pdf(None)),
        ])

        contenedor_subvista_olas = ft.Container(content=subvista_resumen)
        col_principal_picking = ft.Column(
            [barra_proceso, contenedor_subvista_olas],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self.vista = ft.Container(
            padding=ft.Padding.only(left=16, top=14, right=16, bottom=16),
            bgcolor=UI["bg"],
            content=col_principal_picking,
            expand=True,
        )
        self.contenedor = contenedor_subvista_olas
        self.sub_resumen = subvista_resumen
        self.sub_extraccion = subvista_extraccion
        self.sub_seguimiento = subvista_seguimiento
        self.sub_facturacion = subvista_facturacion
        self.titulo_pagina = titulo_pagina
        self.subtitulo_pagina = subtitulo_pagina
        self.acciones_pagina = acciones_pagina
        self._acciones_por_pagina = [
            [btn_dia_resumen, btn_limpiar_dia_resumen, btn_actualizar],
            [btn_actualizar],
            [menu_exportar_seguimiento, btn_actualizar],
            [btn_actualizar],
        ]
        acciones_pagina.controls = list(self._acciones_por_pagina[0])
        self._checks_liberacion = checks_liberacion
        self._checks_facturacion = checks_facturacion
        self._olas_extraidas_ns = olas_extraidas_ns
        self.cargar_monitor_packing_dual_func = cargar_monitor_packing_dual

    def cargar_monitor_packing_dual(self, e=None):
        self.cargar_monitor_packing_dual_func(e)

    def sel_sub_olas(self, idx: int):
        idx_ok = idx if 0 <= idx <= 3 else 0
        vistas = [self.sub_resumen, self.sub_extraccion, self.sub_seguimiento, self.sub_facturacion]
        titulos = [
            ("Resumen operativo", "Estado de las órdenes por etapa y corte horario."),
            ("Crear y liberar olas", "Traiga las órdenes de NetSuite o del Excel de traslado y libérelas a los terminales RF."),
            ("Seguimiento picking / packing", "Busque una OV u OT y vea en qué etapa está."),
            ("Facturación NetSuite", "Órdenes empacadas: descargue el Excel para NetSuite y confirme la facturación."),
        ]
        if idx_ok != 1:
            for chk in self._checks_liberacion.values():
                try:
                    chk.value = False
                except Exception:
                    pass
        # Un mismo control no puede estar en dos pantallas: el encabezado los toma de la pantalla activa
        self.acciones_pagina.controls = list(self._acciones_por_pagina[idx_ok])
        self.contenedor.content = vistas[idx_ok]
        self.titulo_pagina.value, self.subtitulo_pagina.value = titulos[idx_ok]
        self.cargar_monitor_packing_dual_func()
