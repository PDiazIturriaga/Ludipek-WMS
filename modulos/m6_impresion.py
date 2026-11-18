import os
import shutil
from pathlib import Path
import flet as ft
from dependencias import *
try:
    from servicios.servicio_ubicaciones_etiquetas import (
        generar_ubicaciones_concepcion, generar_pdfs_ubicaciones,
        subir_ubicaciones_supabase, codigo_ubicacion,
    )
except ImportError:
    from servicio_ubicaciones_etiquetas import (
        generar_ubicaciones_concepcion, generar_pdfs_ubicaciones,
        subir_ubicaciones_supabase, codigo_ubicacion,
    )


class ImpresionModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list, selector_cencosud=None):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables
        self.ubicaciones_ccp = generar_ubicaciones_concepcion()
        self._ultima_carpeta_ubicaciones = None

        BG = "#1B2122"; CARD = "#262E30"; INPUT = "#1D2426"; BORDER = "#3B484B"
        WHITE = "#F8FAFC"; MUTED = "#94A3B8"; CYAN = "#38BDF8"; GREEN = "#34D399"; AMBER = "#FBBF24"

        def notificar(texto: str, color: str = "#0284C7"):
            notificar_global(self.page, texto, color)

        def card(contenido):
            c = ft.Container(padding=14, bgcolor=CARD, border_radius=8, border=ft.Border.all(1, BORDER), content=contenido)
            self.tarjetas_adaptables.append(c)
            return c

        def field(label, width=180, value=""):
            return ft.TextField(label=label, width=width, value=value, dense=True, color=WHITE, bgcolor=INPUT,
                                border_color=BORDER, focused_border_color=CYAN,
                                label_style=ft.TextStyle(color=MUTED, size=11))

        def opt(key, text):
            return ft.DropdownOption(key=key, text=text, content=ft.Text(text, color=WHITE, size=12))

        self.txt_lpn = field("Código LPN", 220)
        self.txt_ubi_ind = field("Ubicación individual", 210, "M-01")
        self.txt_totem_pasillo = field("Rack / Pasillo", 110, "M")
        self.txt_totem_col = field("Columna", 100, "01")
        self.txt_totem_niveles = field("Niveles", 90, "6")

        self.dd_ccp_pasillo = ft.Dropdown(label="Rack", width=150, value="TODOS", dense=True, bgcolor=INPUT,
            color=WHITE, border_color=BORDER, options=[opt("TODOS", "TODAS LAS UBICACIONES"), opt("M", "LETRA M"), opt("K", "LETRA K"), opt("J", "LETRA J"), opt("I", "LETRA I"), opt("H", "LETRA H"), opt("G", "LETRA G"), opt("F", "LETRA F"), opt("E", "LETRA E"), opt("D", "LETRA D"), opt("C", "LETRA C"), opt("B", "LETRA B"), opt("A", "LETRA A")] + [opt(f"{i:02d}", f"COLUMNA {i:02d}") for i in range(5,16)])
        self.dd_ccp_nivel = ft.Dropdown(label="Modalidad", width=210, value="PICKING", dense=True, bgcolor=INPUT,
            color=WHITE, border_color=BORDER, options=[opt("PICKING","UBICACIONES A PISO")])
        self.lbl_ccp_estado = ft.Text("Maestra preparada: 57 ubicaciones a piso. Columnas 01-04 con letra; columnas 05-15 solo número.", color=GREEN, size=11, weight=ft.FontWeight.BOLD)
        self.lbl_ccp_resumen = ft.Text("Columnas 01-04: 46 ubicaciones con letra | Columnas 05-15: 11 ubicaciones numéricas", color=CYAN, size=12, weight=ft.FontWeight.BOLD)

        def imprimir_lpn(e=None):
            cod = (self.txt_lpn.value or "").strip().upper()
            if not cod:
                notificar("Ingrese un LPN.", "#D97706"); return
            reimprimir_desde_fila_global(self.page, cod)

        def imprimir_ubicacion_unica(e=None):
            cod = (self.txt_ubi_ind.value or "").strip().upper()
            if not cod:
                notificar("Ingrese una ubicación.", "#D97706"); return
            try:
                zona = f"RACK {cod.split('-')[0]}"
                supabase.table("bodega_ubicaciones").upsert({"codigo_ubicacion":cod,"zona":zona,"bodega":"Bodega Concepcion"}, on_conflict="bodega,codigo_ubicacion").execute()
                ruta = generar_pdf_etiqueta_ubicacion_individual(cod, zona)
                descargar_o_abrir_archivo(self.page, ruta)
                notificar(f"Ubicación {cod} guardada e impresa.", "#047857")
            except Exception as ex:
                notificar(f"Error generando ubicación: {ex}", "#B91C1C")

        def imprimir_totem(e=None):
            pas = (self.txt_totem_pasillo.value or "").strip().upper()
            col = (self.txt_totem_col.value or "").strip().upper()
            try: niv = max(1, min(9, int(self.txt_totem_niveles.value or 6)))
            except Exception: niv = 6
            if not pas or not col:
                notificar("Indique rack y columna.", "#D97706"); return
            ruta = generar_pdf_totem_rack(pas, col, niv)
            descargar_o_abrir_archivo(self.page, ruta)
            notificar(f"Tótem generado para {pas}-{col}.", "#047857")

        def _ubicaciones_filtradas():
            pas = None if self.dd_ccp_pasillo.value == "TODOS" else self.dd_ccp_pasillo.value
            nivel = self.dd_ccp_nivel.value or "TODOS"
            data = [u for u in self.ubicaciones_ccp if pas is None or u.pasillo == pas]
            if nivel == "PICKING": data = [u for u in data if u.nivel == 1]
            elif nivel == "ALTURA": data = [u for u in data if u.nivel > 1]
            elif nivel.startswith("N"): data = [u for u in data if u.nivel == int(nivel[1:])]
            return data

        def generar_archivos_ccp(e=None):
            data = _ubicaciones_filtradas()
            if not data:
                notificar("No hay ubicaciones para los filtros elegidos.", "#D97706"); return
            try:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                out = Path("reportes_ubicaciones") / f"CCP_{stamp}"
                pas = None if self.dd_ccp_pasillo.value == "TODOS" else self.dd_ccp_pasillo.value
                archivos = generar_pdfs_ubicaciones(self.ubicaciones_ccp, str(out), pas, self.dd_ccp_nivel.value or "TODOS")
                zip_path = shutil.make_archive(str(out), "zip", root_dir=str(out))
                self._ultima_carpeta_ubicaciones = str(out)
                descargar_o_abrir_archivo(self.page, zip_path)
                self.lbl_ccp_estado.value = f"Generados {len(archivos)} PDF, {len(data)} etiquetas. Archivo: {zip_path}"
                self.lbl_ccp_estado.color = GREEN
                self.page.update()
                notificar(f"Etiquetas CCP generadas: {len(data)} posiciones.", "#047857")
            except Exception as ex:
                notificar(f"Error generando etiquetas CCP: {ex}", "#B91C1C")

        def subir_ccp_supabase(e=None):
            data = _ubicaciones_filtradas()
            try:
                total = subir_ubicaciones_supabase(supabase, data)
                self.lbl_ccp_estado.value = f"Supabase actualizado: {total} ubicaciones en bodega_ubicaciones."
                self.lbl_ccp_estado.color = GREEN
                self.page.update()
                notificar(f"{total} ubicaciones de Concepción cargadas/actualizadas.", "#047857")
            except Exception as ex:
                notificar(f"Error subiendo ubicaciones a Supabase: {ex}", "#B91C1C")

        self.sub_lpn = card(ft.Column([
            ft.Text("IMPRESIÓN DE PALLETS LPN", color=WHITE, size=14, weight=ft.FontWeight.BOLD),
            ft.Row([self.txt_lpn, boton_primario("IMPRIMIR LPN 15x10", ft.Icons.PRINT_OUTLINED, imprimir_lpn, "#0F766E")], wrap=True)
        ], spacing=12))

        self.sub_ubicaciones = ft.Column([
            card(ft.Column([
                ft.Row([ft.Icon(ft.Icons.WAREHOUSE_ROUNDED, color=CYAN),
                        ft.Column([ft.Text("MAESTRA Y ETIQUETAS DE UBICACIONES - BODEGA CONCEPCIÓN", color=WHITE, size=14, weight=ft.FontWeight.W_900),
                                   ft.Text("Nomenclatura real: columnas 01-04 usan letra+número (M-01, K-01); columnas 05-15 usan solo número (05, 06...15).", color=MUTED, size=11)], spacing=2)], spacing=10),
                ft.Divider(color=BORDER),
                ft.Row([self.dd_ccp_pasillo, self.dd_ccp_nivel,
                        boton_primario("GENERAR PDFs + ZIP", ft.Icons.PICTURE_AS_PDF_OUTLINED, generar_archivos_ccp, "#0284C7"),
                        boton_primario("SUBIR A SUPABASE", ft.Icons.CLOUD_UPLOAD_OUTLINED, subir_ccp_supabase, "#047857")], wrap=True, spacing=8),
                self.lbl_ccp_resumen, self.lbl_ccp_estado,
            ], spacing=10)),
            card(ft.Column([
                ft.Text("IMPRESIÓN INDIVIDUAL Y TÓTEM", color=WHITE, size=13, weight=ft.FontWeight.BOLD),
                ft.Row([self.txt_ubi_ind, boton_primario("GUARDAR + IMPRIMIR UBICACIÓN", ft.Icons.LOCATION_ON_OUTLINED, imprimir_ubicacion_unica, "#0F766E")], wrap=True),
                ft.Row([self.txt_totem_pasillo, self.txt_totem_col, self.txt_totem_niveles,
                        boton_primario("GENERAR TÓTEM A4", ft.Icons.QR_CODE_2_ROUNDED, imprimir_totem, "#4F46E5")], wrap=True),
            ], spacing=10)),
        ], spacing=10, scroll=ft.ScrollMode.AUTO)

        self.sub_retail = card(ft.Column([ft.Text("ETIQUETAS B2B RETAIL", color=WHITE, size=14, weight=ft.FontWeight.BOLD), ft.Text("Módulo preparado para Cencosud y formatos B2B.", color=MUTED)], spacing=8))
        self.sub_meli = card(ft.Column([ft.Text("ETIQUETAS E-COMMERCE", color=WHITE, size=14, weight=ft.FontWeight.BOLD), ft.Text("Módulo preparado para Mercado Libre y etiquetas de transporte.", color=MUTED)], spacing=8))

        self.contenedor = ft.Container(content=self.sub_lpn, expand=True)
        self.vista = ft.Container(padding=14, bgcolor=BG, expand=True, content=ft.Column([
            ft.Container(padding=12, bgcolor=CARD, border_radius=8, content=ft.Row([
                ft.Icon(ft.Icons.PRINT_ROUNDED, color=CYAN),
                ft.Text("CENTRO DE IMPRESIÓN Y MAESTRA DE UBICACIONES", color=WHITE, size=15, weight=ft.FontWeight.W_900)
            ], spacing=10)), self.contenedor
        ], spacing=10, expand=True))

    def sel_sub_imp(self, idx: int):
        self.contenedor.content = [self.sub_lpn, self.sub_ubicaciones, self.sub_retail, self.sub_meli][idx]
        self.page.update()
