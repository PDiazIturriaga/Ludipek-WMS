import shutil
from datetime import datetime
from pathlib import Path

import flet as ft

from dependencias import *
from servicio_ubicaciones_etiquetas import (
    generar_ubicaciones_concepcion,
    generar_pdfs_ubicaciones,
)


class ImpresionModulo:
    """Centro de impresión WMS.

    La sección de ubicaciones de Concepción es exclusivamente de impresión:
    no crea ubicaciones individuales y no escribe en Supabase.
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

        self.sub_ubicaciones = ft.Column(
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
            return ft.DropdownOption(key=key, text=text)
        except AttributeError:
            return ft.dropdown.Option(key=key, text=text)

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

    def _generar_etiquetas_ccp(self, e=None):
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
            descargar_o_abrir_archivo(self.page, ruta_zip)

            self.lbl_resultado.value = (
                f"Listo: {len(ubicaciones)} etiquetas distribuidas en "
                f"{len(archivos)} PDF. Archivo: {Path(ruta_zip).name}"
            )
            self.lbl_resultado.color = self.GREEN
            self.page.update()
            self._notificar(
                f"Se generaron {len(ubicaciones)} etiquetas de Concepción.",
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

    def sel_sub_imp(self, idx: int):
        vistas = [
            self.sub_lpn,
            self.sub_ubicaciones,
            self.sub_retail,
            self.sub_meli,
        ]
        indice = idx if 0 <= idx < len(vistas) else 0
        self.contenedor.content = vistas[indice]
        self.page.update()
