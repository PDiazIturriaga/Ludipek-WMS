import shutil
from datetime import datetime
from pathlib import Path

import flet as ft

from dependencias import *
from servicio_ubicaciones_etiquetas import (
    generar_ubicaciones_concepcion,
    generar_pdfs_ubicaciones,
    generar_pdfs_ubicaciones_stgo,
    describir_ubicacion_stgo,
)


class ImpresionModulo:
    """Centro de impresión WMS.

    Ubicaciones: una pestaña por bodega.
      · Santiago: lee las ubicaciones reales de bodega_ubicaciones (racks A-H y arena).
      · Concepción: ubicaciones de piso fijas (no escribe en Supabase).
    """

    def __init__(
        self,
        page: ft.Page,
        tarjetas_adaptables: list,
        kpis_adaptables: list,
        selector_cencosud=None,
    ):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables
        self.selector_cencosud = selector_cencosud
        self.ubicaciones_ccp = generar_ubicaciones_concepcion()
        # FilePicker con src_bytes fuerza una descarga real en Flet Web/Render.
        self.file_picker = ft.FilePicker()
        if hasattr(self.page, "services") and self.file_picker not in self.page.services:
            self.page.services.append(self.file_picker)

        # Paleta visual común del WMS.
        self.BG = "#1B2122"
        self.CARD = "#262E30"
        self.INPUT = "#1D2426"
        self.BORDER = "#3B484B"
        self.WHITE = "#F8FAFC"
        self.MUTED = "#94A3B8"
        self.CYAN = "#38BDF8"
        self.GREEN = "#34D399"
        self.AMBER = "#FBBF24"
        self.RED = "#EF4444"

        # Controles generales.
        self.txt_lpn = self._campo("Código LPN", width=240)

        # Panel de selección de ubicaciones CCP.
        self.dd_alcance = ft.Dropdown(
            label="Qué desea imprimir",
            width=245,
            value="TODAS",
            dense=True,
            bgcolor=self.INPUT,
            color=self.WHITE,
            border_color=self.BORDER,
            focused_border_color=self.CYAN,
            text_style=ft.TextStyle(color=self.WHITE, size=12),
            options=[
                self._opcion("TODAS", "TODAS LAS UBICACIONES (57)"),
                self._opcion("LETRA", "UNA LETRA: columnas 01 a 04"),
                self._opcion("COLUMNAS", "COLUMNAS NUMÉRICAS: 05 a 15"),
            ],
            on_select=self._actualizar_panel_filtros,
        )
        self.dd_letra = ft.Dropdown(
            label="Letra",
            width=160,
            value="M",
            dense=True,
            bgcolor=self.INPUT,
            color=self.WHITE,
            border_color=self.BORDER,
            focused_border_color=self.CYAN,
            text_style=ft.TextStyle(color=self.WHITE, size=12),
            options=[self._opcion(letra, f"LETRA {letra}") for letra in "MKJIHGFEDCBA"],
            visible=False,
        )
        columnas = [f"{numero:02d}" for numero in range(5, 16)]
        self.dd_columna_desde = ft.Dropdown(
            label="Desde columna",
            width=165,
            value="05",
            dense=True,
            bgcolor=self.INPUT,
            color=self.WHITE,
            border_color=self.BORDER,
            focused_border_color=self.CYAN,
            text_style=ft.TextStyle(color=self.WHITE, size=12),
            options=[self._opcion(c, f"COLUMNA {c}") for c in columnas],
            visible=False,
        )
        self.dd_columna_hasta = ft.Dropdown(
            label="Hasta columna",
            width=165,
            value="15",
            dense=True,
            bgcolor=self.INPUT,
            color=self.WHITE,
            border_color=self.BORDER,
            focused_border_color=self.CYAN,
            text_style=ft.TextStyle(color=self.WHITE, size=12),
            options=[self._opcion(c, f"COLUMNA {c}") for c in columnas],
            visible=False,
        )
        self.lbl_seleccion = ft.Text(
            "Se generarán 57 etiquetas: 46 con letra y 11 numéricas.",
            size=11,
            color=self.CYAN,
            weight=ft.FontWeight.BOLD,
        )
        self.lbl_resultado = ft.Text(
            "Seleccione el alcance y presione GENERAR ETIQUETAS PDF.",
            size=11,
            color=self.MUTED,
        )

        self.sub_lpn = self._tarjeta(
            ft.Column(
                [
                    self._titulo_seccion(
                        ft.Icons.QR_CODE_2_ROUNDED,
                        "ETIQUETAS DE PALLET LPN",
                        "Reimpresión de etiqueta logística 15 × 10 cm.",
                    ),
                    ft.Divider(color=self.BORDER, height=2),
                    ft.Row(
                        [
                            self.txt_lpn,
                            boton_primario(
                                "IMPRIMIR LPN",
                                ft.Icons.PRINT_OUTLINED,
                                self._imprimir_lpn,
                                "#0F766E",
                            ),
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                ],
                spacing=12,
            )
        )

        self.panel_ccp = ft.Column(
            [
                self._tarjeta(
                    ft.Column(
                        [
                            self._titulo_seccion(
                                ft.Icons.LOCATION_ON_ROUNDED,
                                "ETIQUETAS DE UBICACIONES - BODEGA CONCEPCIÓN",
                                "Columnas 01 a 04 utilizan letra y número. Columnas 05 a 15 utilizan solo el número.",
                            ),
                            ft.Divider(color=self.BORDER, height=2),
                            ft.Container(
                                padding=12,
                                bgcolor="#202728",
                                border_radius=8,
                                border=ft.Border.all(1, self.BORDER),
                                content=ft.Column(
                                    [
                                        ft.Text(
                                            "SELECCIÓN DE ETIQUETAS",
                                            size=11,
                                            color=self.WHITE,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Row(
                                            [
                                                self.dd_alcance,
                                                self.dd_letra,
                                                self.dd_columna_desde,
                                                self.dd_columna_hasta,
                                            ],
                                            wrap=True,
                                            spacing=8,
                                            run_spacing=8,
                                        ),
                                        self.lbl_seleccion,
                                    ],
                                    spacing=8,
                                ),
                            ),
                            ft.Row(
                                [
                                    boton_primario(
                                        "GENERAR ETIQUETAS PDF",
                                        ft.Icons.PICTURE_AS_PDF_OUTLINED,
                                        self._generar_etiquetas_ccp,
                                        "#0284C7",
                                    ),
                                ],
                                wrap=True,
                            ),
                            ft.Container(
                                padding=10,
                                bgcolor="#172022",
                                border_radius=7,
                                border=ft.Border.all(1, self.BORDER),
                                content=ft.Row(
                                    [
                                        ft.Icon(
                                            ft.Icons.INFO_OUTLINE_ROUNDED,
                                            size=18,
                                            color=self.CYAN,
                                        ),
                                        ft.Column(
                                            [
                                                ft.Text(
                                                    "MAESTRA DE IMPRESIÓN",
                                                    size=10,
                                                    color=self.MUTED,
                                                    weight=ft.FontWeight.BOLD,
                                                ),
                                                self.lbl_resultado,
                                            ],
                                            spacing=2,
                                            expand=True,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                            ),
                        ],
                        spacing=10,
                    )
                )
            ],
            spacing=10,
        )

        self._construir_panel_santiago()
        es_ccp = "CONCEPCION" in obtener_bodega_activa(self.page).upper().replace("Ó", "O")
        self.cont_ubicaciones = ft.Container(content=self.panel_ccp if es_ccp else self.panel_stgo, expand=True)
        self.pestanas_bodega = ui_pestanas(
            [("Bodega Santiago", ft.Icons.WAREHOUSE_ROUNDED), ("Bodega Concepción", ft.Icons.LOCATION_CITY_ROUNDED)],
            self._cambiar_bodega_ubicaciones, 1 if es_ccp else 0,
        )
        self.sub_ubicaciones = ft.Column(
            [
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=10, vertical=6), bgcolor=self.CARD, border_radius=8,
                    border=ft.Border.all(1, self.BORDER),
                    content=ft.Row([ft.Text("Etiquetas de ubicación de:", size=12, color=self.MUTED), self.pestanas_bodega],
                                   spacing=12, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ),
                self.cont_ubicaciones,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # Se mantienen las pestañas de retail/e-commerce para no romper main.py.
        self.sub_retail = self._tarjeta(
            ft.Column(
                [
                    self._titulo_seccion(
                        ft.Icons.STORE_OUTLINED,
                        "ETIQUETAS B2B RETAIL",
                        "Formatos logísticos para clientes retail.",
                    ),
                    ft.Text(
                        "Seleccione el flujo correspondiente desde el módulo comercial antes de imprimir.",
                        color=self.MUTED,
                        size=11,
                    ),
                ],
                spacing=10,
            )
        )
        self.sub_meli = self._tarjeta(
            ft.Column(
                [
                    self._titulo_seccion(
                        ft.Icons.LOCAL_SHIPPING_OUTLINED,
                        "ETIQUETAS E-COMMERCE",
                        "Formatos de transporte y última milla.",
                    ),
                    ft.Text(
                        "La impresión se habilita desde la orden preparada para despacho.",
                        color=self.MUTED,
                        size=11,
                    ),
                ],
                spacing=10,
            )
        )

        self.contenedor = ft.Container(content=self.sub_lpn, expand=True)
        self.vista = ft.Container(
            padding=14,
            bgcolor=self.BG,
            expand=True,
            content=ft.Column(
                [
                    ft.Container(
                        padding=12,
                        bgcolor=self.CARD,
                        border_radius=8,
                        border=ft.Border.all(1, self.BORDER),
                        content=ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.PRINT_ROUNDED,
                                    color=self.CYAN,
                                    size=24,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(
                                            "CENTRO DE IMPRESIÓN",
                                            color=self.WHITE,
                                            size=15,
                                            weight=ft.FontWeight.W_900,
                                        ),
                                        ft.Text(
                                            "LPN, ubicaciones y documentos logísticos",
                                            color=self.MUTED,
                                            size=10.5,
                                        ),
                                    ],
                                    spacing=1,
                                ),
                            ],
                            spacing=10,
                        ),
                    ),
                    self.contenedor,
                ],
                spacing=10,
                expand=True,
            ),
        )

    def _opcion(self, key: str, text: str):
        """Compatible con versiones recientes y anteriores de Flet."""
        try:
            return ft.DropdownOption(
                key=key,
                text=text,
                content=ft.Text(text, color=self.WHITE, size=12),
            )
        except AttributeError:
            return ft.dropdown.Option(
                key=key,
                text=text,
                content=ft.Text(text, color=self.WHITE, size=12),
            )

    def _campo(self, label: str, width: int = 180, value: str = ""):
        return ft.TextField(
            label=label,
            value=value,
            width=width,
            dense=True,
            bgcolor=self.INPUT,
            color=self.WHITE,
            border_color=self.BORDER,
            focused_border_color=self.CYAN,
            label_style=ft.TextStyle(color=self.MUTED, size=11),
        )

    def _tarjeta(self, contenido):
        tarjeta = ft.Container(
            padding=14,
            bgcolor=self.CARD,
            border_radius=8,
            border=ft.Border.all(1, self.BORDER),
            content=contenido,
        )
        self.tarjetas_adaptables.append(tarjeta)
        return tarjeta

    def _titulo_seccion(self, icono, titulo: str, detalle: str):
        return ft.Row(
            [
                ft.Icon(icono, color=self.CYAN, size=23),
                ft.Column(
                    [
                        ft.Text(
                            titulo,
                            size=14,
                            color=self.WHITE,
                            weight=ft.FontWeight.W_900,
                        ),
                        ft.Text(detalle, size=10.5, color=self.MUTED),
                    ],
                    spacing=1,
                    expand=True,
                ),
            ],
            spacing=10,
        )

    def _notificar(self, mensaje: str, color: str = "#0284C7"):
        notificar_global(self.page, mensaje, color)

    def _imprimir_lpn(self, e=None):
        codigo = (self.txt_lpn.value or "").strip().upper()
        if not codigo:
            self._notificar("Ingrese un código LPN.", "#D97706")
            return
        try:
            reimprimir_desde_fila_global(self.page, codigo)
        except Exception as ex:
            self._notificar(f"No se pudo imprimir el LPN: {ex}", "#B91C1C")

    def _actualizar_panel_filtros(self, e=None):
        modo = self.dd_alcance.value or "TODAS"
        self.dd_letra.visible = modo == "LETRA"
        self.dd_columna_desde.visible = modo == "COLUMNAS"
        self.dd_columna_hasta.visible = modo == "COLUMNAS"

        if modo == "TODAS":
            self.lbl_seleccion.value = (
                "Se generarán 57 etiquetas: 46 con letra y 11 numéricas."
            )
        elif modo == "LETRA":
            letra = self.dd_letra.value or "M"
            cantidad = len(
                [ubicacion for ubicacion in self.ubicaciones_ccp if ubicacion.letra == letra]
            )
            self.lbl_seleccion.value = (
                f"Se generarán {cantidad} etiquetas para la letra {letra}."
            )
        else:
            desde = int(self.dd_columna_desde.value or 5)
            hasta = int(self.dd_columna_hasta.value or 15)
            if desde > hasta:
                desde, hasta = hasta, desde
            self.lbl_seleccion.value = (
                f"Se generarán {hasta - desde + 1} etiquetas: columnas {desde:02d} a {hasta:02d}."
            )
        self.page.update()

    def _ubicaciones_seleccionadas(self):
        modo = self.dd_alcance.value or "TODAS"
        if modo == "TODAS":
            return list(self.ubicaciones_ccp), "TODAS"

        if modo == "LETRA":
            letra = str(self.dd_letra.value or "M").upper()
            ubicaciones = [
                ubicacion
                for ubicacion in self.ubicaciones_ccp
                if ubicacion.letra == letra
            ]
            return ubicaciones, letra

        desde = int(self.dd_columna_desde.value or 5)
        hasta = int(self.dd_columna_hasta.value or 15)
        if desde > hasta:
            desde, hasta = hasta, desde
        ubicaciones = [
            ubicacion
            for ubicacion in self.ubicaciones_ccp
            if not ubicacion.letra and desde <= ubicacion.columna <= hasta
        ]
        return ubicaciones, f"{desde:02d}-{hasta:02d}"

    async def _generar_etiquetas_ccp(self, e=None):
        ubicaciones, nombre_seleccion = self._ubicaciones_seleccionadas()
        if not ubicaciones:
            self._notificar(
                "No existen ubicaciones para la selección indicada.",
                "#D97706",
            )
            return

        try:
            marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S")
            carpeta = (
                Path("reportes_ubicaciones")
                / f"CCP_{nombre_seleccion}_{marca_tiempo}"
            )
            archivos = generar_pdfs_ubicaciones(
                ubicaciones,
                str(carpeta),
                None,
                "PISO",
            )
            if not archivos:
                raise RuntimeError("El generador no produjo archivos PDF.")

            ruta_zip = shutil.make_archive(
                str(carpeta),
                "zip",
                root_dir=str(carpeta),
            )
            nombre_zip = Path(ruta_zip).name
            bytes_zip = Path(ruta_zip).read_bytes()
            destino = await self.file_picker.save_file(
                dialog_title="Guardar etiquetas de ubicaciones",
                file_name=nombre_zip,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["zip"],
                src_bytes=bytes_zip,
            )

            if destino:
                detalle_descarga = f"Guardado en: {destino}"
            else:
                # En navegador, save_file puede devolver None aunque la descarga haya comenzado.
                detalle_descarga = "Descarga enviada al navegador. Revise Descargas."
            self.lbl_resultado.value = (
                f"Listo: {len(ubicaciones)} etiquetas distribuidas en "
                f"{len(archivos)} PDF. {detalle_descarga}"
            )
            self.lbl_resultado.color = self.GREEN
            self.page.update()
            self._notificar(
                f"Se generaron {len(ubicaciones)} etiquetas. La descarga del ZIP fue solicitada al navegador.",
                "#047857",
            )
        except Exception as ex:
            self.lbl_resultado.value = f"Error: {ex}"
            self.lbl_resultado.color = self.RED
            self.page.update()
            self._notificar(
                f"Error generando etiquetas de ubicaciones: {ex}",
                "#B91C1C",
            )

    # ==================================================================
    # UBICACIONES BODEGA SANTIAGO (racks y arena, desde bodega_ubicaciones)
    # ==================================================================
    def _dd(self, label: str, width: int, opciones: list, value=None, visible=True):
        return ft.Dropdown(
            label=label, width=width, value=value, dense=True, visible=visible,
            bgcolor=self.INPUT, color=self.WHITE, border_color=self.BORDER, focused_border_color=self.CYAN,
            text_style=ft.TextStyle(color=self.WHITE, size=12),
            options=[self._opcion(k, t) for k, t in opciones],
            on_select=self._actualizar_seleccion_stgo,
        )

    def _construir_panel_santiago(self):
        self.ubic_stgo = []          # [describir_ubicacion_stgo(...)]
        self.dd_zona_stgo = self._dd("Rack o zona", 250, [("TODOS_RACKS", "TODOS LOS RACKS")], "TODOS_RACKS")
        self.dd_nivel_stgo = self._dd("Nivel", 190, [("TODOS", "TODOS LOS NIVELES"), ("PICKING", "SOLO PICKING (01)"),
                                                    ("RESERVA", "SOLO RESERVA (02+)")], "TODOS")
        self.dd_desde_stgo = self._dd("Desde columna", 150, [], None)
        self.dd_hasta_stgo = self._dd("Hasta columna", 150, [], None)
        self.txt_codigos_stgo = ft.TextField(
            label="O escriba ubicaciones puntuales (ej. H-02-01, BE-03-12)", width=420, dense=True,
            bgcolor=self.INPUT, color=self.WHITE, border_color=self.BORDER, focused_border_color=self.CYAN,
            label_style=ft.TextStyle(color=self.MUTED, size=11), on_change=self._actualizar_seleccion_stgo,
        )
        self.lbl_sel_stgo = ft.Text("Cargando ubicaciones de Bodega Santiago…", size=11, color=self.CYAN,
                                    weight=ft.FontWeight.BOLD)
        self.lbl_res_stgo = ft.Text("Elija qué imprimir y presione GENERAR ETIQUETAS PDF.", size=11, color=self.MUTED)
        leyenda = ft.Row([
            ft.Row([ft.Container(width=12, height=12, border_radius=3, bgcolor=c), ft.Text(t, size=11, color=self.MUTED)],
                   spacing=5, tight=True)
            for c, t in [("#047857", "Picking (nivel 01)"), ("#1E293B", "Reserva"), ("#855C2D", "Arena"), ("#991B1B", "Mermas arena")]
        ], spacing=14, wrap=True)
        self.panel_stgo = self._tarjeta(ft.Column([
            self._titulo_seccion(
                ft.Icons.LOCATION_ON_ROUNDED,
                "ETIQUETAS DE UBICACIONES - BODEGA SANTIAGO",
                "Racks A a H (rack-columna-nivel, el nivel 01 es picking) y zonas de arena (MK, ME, BE). "
                "Una etiqueta 20 × 10 cm por ubicación con código QR.",
            ),
            ft.Divider(color=self.BORDER, height=2),
            ft.Container(
                padding=12, bgcolor="#202728", border_radius=8, border=ft.Border.all(1, self.BORDER),
                content=ft.Column([
                    ft.Text("SELECCIÓN DE ETIQUETAS", size=11, color=self.WHITE, weight=ft.FontWeight.BOLD),
                    ft.Row([self.dd_zona_stgo, self.dd_nivel_stgo, self.dd_desde_stgo, self.dd_hasta_stgo],
                           wrap=True, spacing=8, run_spacing=8),
                    self.txt_codigos_stgo,
                    self.lbl_sel_stgo,
                    leyenda,
                ], spacing=8),
            ),
            ft.Row([
                boton_primario("GENERAR ETIQUETAS PDF", ft.Icons.PICTURE_AS_PDF_OUTLINED, self._generar_etiquetas_stgo, "#0284C7"),
                boton_primario("RECARGAR UBICACIONES", ft.Icons.REFRESH_ROUNDED, lambda e: self._cargar_ubicaciones_stgo(), "#475569"),
            ], wrap=True),
            ft.Container(
                padding=10, bgcolor="#172022", border_radius=7, border=ft.Border.all(1, self.BORDER),
                content=ft.Row([
                    ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, size=18, color=self.CYAN),
                    ft.Column([ft.Text("RESULTADO", size=10, color=self.MUTED, weight=ft.FontWeight.BOLD), self.lbl_res_stgo],
                              spacing=2, expand=True),
                ], spacing=8),
            ),
        ], spacing=10))

    def _cargar_ubicaciones_stgo(self):
        try:
            filas = leer_tabla_paginada(lambda: supabase.table("bodega_ubicaciones")
                                        .select("codigo_ubicacion, bodega").eq("bodega", "Bodega Santiago"))
        except Exception as ex:
            self.lbl_sel_stgo.value = f"No se pudieron leer las ubicaciones: {ex}"
            self.lbl_sel_stgo.color = self.RED
            self.page.update()
            return
        codigos = sorted({str(f.get("codigo_ubicacion") or "").strip().upper() for f in filas
                          if f.get("codigo_ubicacion") and not str(f.get("codigo_ubicacion")).upper().startswith("ZONA")})
        self.ubic_stgo = [describir_ubicacion_stgo(c) for c in codigos]
        zonas = []
        for d in self.ubic_stgo:
            if d["grupo"] not in [z[0] for z in zonas]:
                zonas.append((d["grupo"], d["zona"]))
        orden = lambda z: (0 if z[0].startswith("RACK_") else 1 if z[0].startswith("ARENA_") else 2, z[0])
        opciones = [("TODOS_RACKS", f"TODOS LOS RACKS ({sum(1 for d in self.ubic_stgo if d['grupo'].startswith('RACK_'))})")]
        for g, nom in sorted(zonas, key=orden):
            n = sum(1 for d in self.ubic_stgo if d["grupo"] == g)
            opciones.append((g, f"{nom} ({n})"))
        self.dd_zona_stgo.options = [self._opcion(k, t) for k, t in opciones]
        if self.dd_zona_stgo.value not in [k for k, _ in opciones]:
            self.dd_zona_stgo.value = "TODOS_RACKS"
        self._actualizar_seleccion_stgo()

    def _actualizar_seleccion_stgo(self, e=None):
        zona = self.dd_zona_stgo.value or "TODOS_RACKS"
        es_rack = zona.startswith("RACK_") or zona == "TODOS_RACKS"
        es_arena = zona.startswith("ARENA_")
        self.dd_nivel_stgo.visible = es_rack
        self.dd_desde_stgo.visible = self.dd_hasta_stgo.visible = zona.startswith("RACK_") or es_arena
        etiqueta = "fila" if es_arena else "columna"
        self.dd_desde_stgo.label = f"Desde {etiqueta}"
        self.dd_hasta_stgo.label = f"Hasta {etiqueta}"
        if self.dd_desde_stgo.visible:
            nums = sorted({d["columna"] for d in self.ubic_stgo if d["grupo"] == zona})
            claves = [f"{n:02d}" for n in nums]
            opts = [(c, f"{etiqueta.upper()} {c}") for c in claves]
            if [o.key for o in (self.dd_desde_stgo.options or [])] != claves:
                self.dd_desde_stgo.options = [self._opcion(k, t) for k, t in opts]
                self.dd_hasta_stgo.options = [self._opcion(k, t) for k, t in opts]
                self.dd_desde_stgo.value = claves[0] if claves else None
                self.dd_hasta_stgo.value = claves[-1] if claves else None
        sel = self._seleccion_stgo()
        if (self.txt_codigos_stgo.value or "").strip():
            no_existen = [c for c in self._codigos_escritos() if c not in {d["codigo"] for d in self.ubic_stgo}]
            self.lbl_sel_stgo.value = (f"Se generarán {len(sel)} etiqueta(s) de las ubicaciones escritas."
                                       + (f" No existen en la maestra: {', '.join(no_existen[:6])}" if no_existen else ""))
            self.lbl_sel_stgo.color = self.AMBER if no_existen else self.CYAN
        else:
            pick = sum(1 for d in sel if d["tipo"] == "PICKING")
            self.lbl_sel_stgo.value = (f"Se generarán {len(sel)} etiqueta(s)"
                                       + (f": {pick} de picking y {len(sel) - pick} de reserva." if es_rack else ".")
                                       if sel else "No hay ubicaciones para esta selección.")
            self.lbl_sel_stgo.color = self.CYAN if sel else self.AMBER
        self.page.update()

    def _codigos_escritos(self) -> list:
        texto = (self.txt_codigos_stgo.value or "").upper().replace(";", ",").replace("\n", ",")
        return [c.strip().replace(" ", "") for c in texto.split(",") if c.strip()]

    def _seleccion_stgo(self) -> list:
        escritos = self._codigos_escritos()
        if escritos:
            existentes = {d["codigo"]: d for d in self.ubic_stgo}
            return [existentes[c] for c in dict.fromkeys(escritos) if c in existentes]
        zona = self.dd_zona_stgo.value or "TODOS_RACKS"
        if zona == "TODOS_RACKS":
            sel = [d for d in self.ubic_stgo if d["grupo"].startswith("RACK_")]
        else:
            sel = [d for d in self.ubic_stgo if d["grupo"] == zona]
        if self.dd_desde_stgo.visible and self.dd_desde_stgo.value and self.dd_hasta_stgo.value:
            a, b = sorted((int(self.dd_desde_stgo.value), int(self.dd_hasta_stgo.value)))
            sel = [d for d in sel if a <= d["columna"] <= b]
        nivel = self.dd_nivel_stgo.value or "TODOS"
        if self.dd_nivel_stgo.visible and nivel != "TODOS":
            sel = [d for d in sel if d["tipo"] == nivel]
        return sel

    async def _generar_etiquetas_stgo(self, e=None):
        sel = self._seleccion_stgo()
        if not sel:
            self._notificar("No hay ubicaciones para la selección indicada.", "#D97706")
            return
        try:
            marca = datetime.now().strftime("%Y%m%d_%H%M%S")
            nombre = "PUNTUALES" if self._codigos_escritos() else (self.dd_zona_stgo.value or "TODOS")
            carpeta = Path("reportes_ubicaciones") / f"STGO_{nombre}_{marca}"
            archivos = generar_pdfs_ubicaciones_stgo([d["codigo"] for d in sel], str(carpeta))
            if not archivos:
                raise RuntimeError("El generador no produjo archivos PDF.")
            ruta_zip = shutil.make_archive(str(carpeta), "zip", root_dir=str(carpeta))
            destino = await self.file_picker.save_file(
                dialog_title="Guardar etiquetas de ubicaciones",
                file_name=Path(ruta_zip).name,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["zip"],
                src_bytes=Path(ruta_zip).read_bytes(),
            )
            detalle = f"Guardado en: {destino}" if destino else "Descarga enviada al navegador. Revise Descargas."
            self.lbl_res_stgo.value = f"Listo: {len(sel)} etiquetas en {len(archivos)} PDF (uno por rack o zona). {detalle}"
            self.lbl_res_stgo.color = self.GREEN
            self.page.update()
            self._notificar(f"Se generaron {len(sel)} etiquetas de Bodega Santiago.", "#047857")
        except Exception as ex:
            self.lbl_res_stgo.value = f"Error: {ex}"
            self.lbl_res_stgo.color = self.RED
            self.page.update()
            self._notificar(f"Error generando etiquetas de ubicaciones: {ex}", "#B91C1C")

    def _cambiar_bodega_ubicaciones(self, idx: int):
        self.cont_ubicaciones.content = self.panel_ccp if idx == 1 else self.panel_stgo
        if idx == 0 and not self.ubic_stgo:
            self._cargar_ubicaciones_stgo()
        self.page.update()

    def sel_sub_imp(self, idx: int):
        vistas = [
            self.sub_lpn,
            self.sub_ubicaciones,
            self.sub_retail,
            self.sub_meli,
        ]
        indice = idx if 0 <= idx < len(vistas) else 0
        self.contenedor.content = vistas[indice]
        if indice == 1 and self.cont_ubicaciones.content is self.panel_stgo and not self.ubic_stgo:
            self._cargar_ubicaciones_stgo()
        self.page.update()
