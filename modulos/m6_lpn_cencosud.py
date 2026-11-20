"""Centro de impresión: etiquetas LPN por bodega y etiquetas/reportes Cencosud B2B.

Se usa como "mixin" de ImpresionModulo (m6_impresion.py). Reemplaza las apps aparte
app_lpn.py y app_cencosud.py: los correlativos viven en Supabase (script 27).
"""
import inspect
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import flet as ft

from dependencias import *
from servicios import etiquetas_impresion as EI

BODEGAS_LPN = [("Bodega Santiago", "Santiago"), ("Bodega Concepcion", "Concepción")]


class PanelesLpnCencosud:
    # ==================================================================
    # utilidades comunes
    # ==================================================================
    def _usuario_pc(self) -> str:
        return str(getattr(self.page, "usuario_actual", "") or "PC")

    def _msg_error(self, ex) -> str:
        msg = str(getattr(ex, "message", None) or ex)
        return msg.replace("WMS: ", "")

    async def _descargar(self, ruta: str, titulo: str, extension: str):
        datos = Path(ruta).read_bytes()
        destino = await self.file_picker.save_file(
            dialog_title=titulo, file_name=Path(ruta).name, file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=[extension], src_bytes=datos,
        )
        return destino or "Descarga enviada al navegador. Revise Descargas."

    def _tabla(self, columnas: list):
        return ft.DataTable(
            heading_row_color="#1D2426", heading_row_height=34, data_row_min_height=34, data_row_max_height=40,
            column_spacing=16, horizontal_margin=10,
            columns=[ft.DataColumn(ft.Text(c, size=10.5, weight=ft.FontWeight.BOLD, color=self.MUTED)) for c in columnas],
            rows=[],
        )

    # ==================================================================
    # 1) LPN POR BODEGA
    # ==================================================================
    def _construir_panel_lpn_nuevos(self):
        es_ccp = "CONCEP" in obtener_bodega_activa(self.page).upper()
        self.bodega_lpn = "Bodega Concepcion" if es_ccp else "Bodega Santiago"
        self.lbl_lpn_ultimo = ft.Text("—", size=22, weight=ft.FontWeight.W_900, color=self.CYAN)
        self.lbl_lpn_proximo = ft.Text("", size=11, color=self.MUTED)
        self.txt_lpn_cantidad = self._campo("¿Cuántos LPN imprimir?", width=200, value="40")
        self.txt_lpn_cantidad.keyboard_type = ft.KeyboardType.NUMBER
        self.lbl_lpn_resultado = ft.Text("", size=11, color=self.MUTED)
        self.tabla_lotes_lpn = self._tabla(["FECHA", "RANGO", "CANT.", "USUARIO", "REIMPRIMIR"])
        self.pestanas_lpn = ui_pestanas(
            [("Bodega Santiago", ft.Icons.WAREHOUSE_ROUNDED), ("Bodega Concepción", ft.Icons.LOCATION_CITY_ROUNDED)],
            self._cambiar_bodega_lpn, 1 if es_ccp else 0,
        )
        return self._tarjeta(ft.Column([
            self._titulo_seccion(ft.Icons.QR_CODE_2_ROUNDED, "GENERAR ETIQUETAS LPN NUEVAS",
                                 "Etiqueta 10 × 20 cm con QR. Cada bodega tiene su propio correlativo "
                                 "(Santiago LPN-1xxxxx · Concepción LPN-5xxxxx) y nunca se repite."),
            ft.Divider(color=self.BORDER, height=2),
            ft.Row([ft.Text("Bodega:", size=12, color=self.MUTED), self.pestanas_lpn], spacing=10, wrap=True),
            ft.ResponsiveRow([
                ft.Container(col={"xs": 12, "md": 5}, padding=12, bgcolor="#202728", border_radius=8,
                             border=ft.Border.all(1, self.BORDER),
                             content=ft.Column([ft.Text("ÚLTIMO LPN IMPRESO", size=10, color=self.MUTED, weight=ft.FontWeight.BOLD),
                                                self.lbl_lpn_ultimo, self.lbl_lpn_proximo], spacing=2)),
                ft.Container(col={"xs": 12, "md": 7}, padding=12, content=ft.Column([
                    ft.Row([self.txt_lpn_cantidad,
                            boton_primario("GENERAR ETIQUETAS", ft.Icons.PICTURE_AS_PDF_OUTLINED, self._generar_lpn_nuevos, "#0F766E")],
                           spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    self.lbl_lpn_resultado,
                ], spacing=8)),
            ], spacing=10, run_spacing=10),
            ft.Text("ÚLTIMAS IMPRESIONES DE ESTA BODEGA", size=10.5, color=self.MUTED, weight=ft.FontWeight.BOLD),
            ui_tabla(self.tabla_lotes_lpn, 220),
        ], spacing=10))

    def _cambiar_bodega_lpn(self, idx: int):
        self.bodega_lpn = BODEGAS_LPN[idx if 0 <= idx < 2 else 0][0]
        self._cargar_estado_lpn()
        self.page.update()

    def _cargar_estado_lpn(self):
        try:
            fila = (supabase.table("wms_correlativos").select("ultimo").eq("clave", f"LPN|{self.bodega_lpn}")
                    .execute().data or [])
            lotes = (supabase.table("wms_lpn_lotes").select("*").eq("bodega", self.bodega_lpn)
                     .order("id", desc=True).limit(15).execute().data or [])
        except Exception as ex:
            self.lbl_lpn_ultimo.value = "—"
            self.lbl_lpn_proximo.value = f"Falta ejecutar 27_correlativos_impresion.sql ({self._msg_error(ex)[:80]})"
            self.tabla_lotes_lpn.rows = []
            return
        if fila:
            ultimo = int(fila[0]["ultimo"])
            self.lbl_lpn_ultimo.value = f"{EI.PREFIJO_LPN}{ultimo}"
            self.lbl_lpn_proximo.value = f"El próximo lote comenzará en {EI.PREFIJO_LPN}{ultimo + 1}"
        filas = []
        for l in lotes:
            filas.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(formatear_fecha_hora_chile(l.get("creado_en")), size=11, color=self.WHITE)),
                ft.DataCell(ft.Text(f"{EI.PREFIJO_LPN}{l['desde']} → {EI.PREFIJO_LPN}{l['hasta']}", size=11,
                                    weight=ft.FontWeight.BOLD, color=self.CYAN)),
                ft.DataCell(ft.Text(str(l.get("cantidad")), size=11, color=self.WHITE)),
                ft.DataCell(ft.Text(str(l.get("usuario") or ""), size=11, color=self.MUTED)),
                ft.DataCell(ft.IconButton(icon=ft.Icons.PRINT_OUTLINED, icon_size=18, icon_color=self.CYAN,
                                          tooltip="Volver a generar este mismo rango (no consume números)",
                                          on_click=lambda e, d=l["desde"], h=l["hasta"]: self.page.run_task(self._reimprimir_lote_lpn, d, h))),
            ]))
        self.tabla_lotes_lpn.rows = filas

    async def _generar_lpn_nuevos(self, e=None):
        try:
            cantidad = int(str(self.txt_lpn_cantidad.value or "").strip())
            if cantidad <= 0 or cantidad > 1000:
                raise ValueError
        except ValueError:
            self._notificar("Ingrese una cantidad entre 1 y 1000.", "#D97706")
            return
        try:
            r = supabase.rpc("wms_reservar_lpn", {"p_bodega": self.bodega_lpn, "p_cantidad": cantidad,
                                                  "p_usuario": self._usuario_pc()}).execute().data or {}
        except Exception as ex:
            msg = self._msg_error(ex)
            if "wms_reservar_lpn" in msg and ("not find" in msg or "does not exist" in msg):
                msg = "falta ejecutar 27_correlativos_impresion.sql en Supabase"
            self._notificar(f"No se pudo reservar el correlativo: {msg}", "#B91C1C")
            return
        await self._emitir_pdf_lpn(int(r["desde"]), int(r["hasta"]))
        self._cargar_estado_lpn()
        self.page.update()

    async def _reimprimir_lote_lpn(self, desde: int, hasta: int):
        await self._emitir_pdf_lpn(int(desde), int(hasta), reimpresion=True)

    async def _emitir_pdf_lpn(self, desde: int, hasta: int, reimpresion: bool = False):
        try:
            carpeta = Path(tempfile.gettempdir()) / "wms_lpn"
            carpeta.mkdir(parents=True, exist_ok=True)
            sufijo = "CCP" if "CONCEP" in self.bodega_lpn.upper() else "STGO"
            ruta = carpeta / f"LPN_{sufijo}_{desde}_al_{hasta}.pdf"
            n = EI.generar_pdf_lpn(desde, hasta, self.bodega_lpn, str(ruta))
            destino = await self._descargar(str(ruta), "Guardar etiquetas LPN", "pdf")
            self.lbl_lpn_resultado.value = (f"{'Reimpresión' if reimpresion else 'Listo'}: {n} etiquetas "
                                            f"{EI.PREFIJO_LPN}{desde} a {EI.PREFIJO_LPN}{hasta}. {destino}")
            self.lbl_lpn_resultado.color = self.GREEN
            self.page.update()
            self._notificar(f"{n} etiquetas LPN generadas ({EI.PREFIJO_LPN}{desde} → {EI.PREFIJO_LPN}{hasta}).", "#047857")
        except Exception as ex:
            self.lbl_lpn_resultado.value = f"Error generando el PDF: {ex}"
            self.lbl_lpn_resultado.color = self.RED
            self.page.update()
            registrar_error_pc("IMPRESION_LPN", f"{type(ex).__name__}: {ex}")

    # ==================================================================
    # 2) CENCOSUD B2B
    # ==================================================================
    def _construir_panel_cencosud(self):
        self.archivo_oc_cencosud = None
        self.lbl_archivo_oc = ft.Text("Ningún archivo seleccionado", size=11.5, color=self.MUTED)
        self.txt_hu_inicial = self._campo("Correlativo HU inicial (próximo)", width=270)
        self.lbl_hu_info = ft.Text("", size=11, color=self.MUTED)
        self.chk_hu_usado = ft.Checkbox(label="Permitir un HU ya usado (reproceso)", value=False,
                                        label_style=ft.TextStyle(size=11, color=self.MUTED))
        self.txt_factura_b2b = self._campo("N° de factura (opcional, formato B2B)", width=270)
        self.lbl_res_cencosud = ft.Text("", size=11, color=self.MUTED)
        self.tabla_ocs_cencosud = self._tabla(["FECHA PROCESO", "OC", "ENTREGA", "HU", "LOCALES", "BULTOS", "DESCARGAR"])

        # Reimpresión
        self.txt_hu_reimp = self._campo("N° de HU (ej. 76661486000001697)", width=290)
        self.dd_bultos_reimp = ft.Dropdown(label="Bulto a reimprimir", width=420, dense=True, bgcolor=self.INPUT,
                                           border_color=self.BORDER, text_style=ft.TextStyle(color=self.WHITE, size=12),
                                           options=[], disabled=True)
        self.filas_reimp = []

        self.selector_oc = ft.FilePicker()
        if hasattr(self.page, "services") and self.selector_oc not in self.page.services:
            self.page.services.append(self.selector_oc)

        generacion = self._tarjeta(ft.Column([
            self._titulo_seccion(ft.Icons.LOCAL_MALL_OUTLINED, "ETIQUETAS CENCOSUD B2B · GENERACIÓN MASIVA",
                                 "Cargue la OC descargada del B2B (.xls). Se genera un HU por local, una etiqueta 15 × 10 cm "
                                 "por empaque, el packing list y el imprimible para el conductor."),
            ft.Divider(color=self.BORDER, height=2),
            ft.Row([ui_boton("Cargar orden B2B (.xls)", ft.Icons.UPLOAD_FILE_ROUNDED, self._elegir_oc_cencosud, "secundario"),
                    self.lbl_archivo_oc], spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([self.txt_hu_inicial, self.txt_factura_b2b], spacing=10, wrap=True),
            self.lbl_hu_info,
            self.chk_hu_usado,
            ft.Row([boton_primario("PROCESAR ETIQUETAS (POR EMPAQUE) Y REPORTES", ft.Icons.PICTURE_AS_PDF_OUTLINED,
                                   self._procesar_oc_cencosud, "#0284C7")], wrap=True),
            self.lbl_res_cencosud,
            ft.Text("ÓRDENES PROCESADAS (se pueden descargar de nuevo)", size=10.5, color=self.MUTED, weight=ft.FontWeight.BOLD),
            ui_tabla(self.tabla_ocs_cencosud, 240),
        ], spacing=10))

        reimpresion = self._tarjeta(ft.Column([
            self._titulo_seccion(ft.Icons.REPLAY_ROUNDED, "REIMPRESIÓN UNITARIA DE HU",
                                 "Busque el HU en el histórico (Supabase) y reimprima todos sus bultos o uno solo."),
            ft.Divider(color=self.BORDER, height=2),
            ft.Row([self.txt_hu_reimp, ui_boton("Buscar HU", ft.Icons.SEARCH_ROUNDED, self._buscar_hu_cencosud, "secundario")],
                   spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.dd_bultos_reimp,
            ft.Row([boton_primario("GENERAR PDF DE REIMPRESIÓN", ft.Icons.PRINT_OUTLINED, self._reimprimir_hu_cencosud, "#2B8A3E"),
                    ui_boton("Importar Historico_Cencosud.xlsx antiguo", ft.Icons.HISTORY_ROUNDED,
                             self._elegir_historico_antiguo, "texto")], spacing=10, wrap=True),
        ], spacing=10))

        return ft.Column([generacion, reimpresion], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

    def _cargar_estado_cencosud(self):
        try:
            fila = supabase.table("wms_correlativos").select("ultimo").eq("clave", "CENCOSUD_HU").execute().data or []
            hist = (supabase.table("wms_cencosud_hu")
                    .select("numero_orden, fecha_entrega, hu, cod_local, empaques_pedidos, fecha_proceso, origen")
                    .order("id", desc=True).limit(1500).execute().data or [])
        except Exception as ex:
            self.lbl_hu_info.value = f"Falta ejecutar 27_correlativos_impresion.sql ({self._msg_error(ex)[:80]})"
            return
        if fila:
            self.ultimo_hu = int(fila[0]["ultimo"])
            if not (self.txt_hu_inicial.value or "").strip():
                self.txt_hu_inicial.value = str(self.ultimo_hu + 1)
            self.lbl_hu_info.value = f"Último HU usado: {self.ultimo_hu}. Próximo disponible: {self.ultimo_hu + 1}."
        # Resumen por OC (y fecha de proceso)
        grupos = {}
        for h in hist:
            clave = (h.get("numero_orden"), str(h.get("fecha_proceso") or "")[:16])
            g = grupos.setdefault(clave, {"oc": h.get("numero_orden"), "proceso": h.get("fecha_proceso"),
                                          "entrega": h.get("fecha_entrega"), "hu": set(), "locales": set(), "bultos": 0})
            g["hu"].add(str(h.get("hu")))
            g["locales"].add(str(h.get("cod_local")))
            g["bultos"] += int(h.get("empaques_pedidos") or 0)
        filas = []
        for g in list(grupos.values())[:25]:
            hus = sorted(g["hu"])
            filas.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(formatear_fecha_hora_chile(g["proceso"]), size=11, color=self.WHITE)),
                ft.DataCell(ft.Text(str(g["oc"]), size=11, weight=ft.FontWeight.BOLD, color=self.CYAN)),
                ft.DataCell(ft.Text(str(g["entrega"] or ""), size=11, color=self.WHITE)),
                ft.DataCell(ft.Text(f"{hus[0]} → {hus[-1]}" if len(hus) > 1 else hus[0], size=11, color=self.WHITE)),
                ft.DataCell(ft.Text(str(len(g["locales"])), size=11, color=self.WHITE)),
                ft.DataCell(ft.Text(str(g["bultos"]), size=11, color=self.WHITE)),
                ft.DataCell(ft.IconButton(icon=ft.Icons.DOWNLOAD_ROUNDED, icon_size=18, icon_color=self.CYAN,
                                          tooltip="Descargar de nuevo etiquetas y reportes de esta OC",
                                          on_click=lambda e, oc=g["oc"], hs=hus: self.page.run_task(self._redescargar_oc, oc, hs))),
            ]))
        self.tabla_ocs_cencosud.rows = filas

    # ---------------- selección de archivos (escritorio o navegador) ----------------
    async def _elegir_archivo(self, extensiones: list):
        """Devuelve la ruta local del archivo elegido (o None)."""
        picker = self.selector_oc
        kw = {"allow_multiple": False, "allowed_extensions": extensiones}
        try:
            if "with_data" in inspect.signature(picker.pick_files).parameters:
                kw["with_data"] = True
        except Exception:
            pass
        res = picker.pick_files(**kw)
        if inspect.isawaitable(res):
            res = await res
        archivos = res if isinstance(res, list) else (getattr(res, "files", None) or [])
        if not archivos:
            return None
        f = archivos[0]
        ruta = getattr(f, "path", None)
        if ruta and os.path.isfile(ruta):
            return ruta
        datos = getattr(f, "bytes", None)
        if datos:
            carpeta = Path(tempfile.gettempdir()) / "wms_uploads"
            carpeta.mkdir(parents=True, exist_ok=True)
            destino = carpeta / os.path.basename(str(getattr(f, "name", "archivo")))
            destino.write_bytes(bytes(datos))
            return str(destino)
        self._notificar("No se pudo leer el archivo en este navegador. Use el programa de escritorio del PC.", "#B91C1C")
        return None

    async def _elegir_oc_cencosud(self, e=None):
        try:
            ruta = await self._elegir_archivo(["xls", "xlsx", "html", "htm"])
        except Exception as ex:
            self._notificar(f"No se pudo abrir el selector: {ex}", "#B91C1C")
            return
        if not ruta:
            return
        self.archivo_oc_cencosud = ruta
        nombre = os.path.basename(ruta)
        self.lbl_archivo_oc.value = nombre if len(nombre) < 60 else nombre[:57] + "..."
        self.lbl_archivo_oc.color = self.WHITE
        self.page.update()

    # ---------------- generación ----------------
    async def _procesar_oc_cencosud(self, e=None):
        if not self.archivo_oc_cencosud:
            self._notificar("Cargue primero el archivo de la orden de compra.", "#D97706")
            return
        try:
            hu_inicial = int(str(self.txt_hu_inicial.value or "").strip())
        except ValueError:
            self._notificar("El correlativo HU inicial debe ser un número.", "#D97706")
            return
        self._cargar_estado_cencosud()
        ultimo = getattr(self, "ultimo_hu", None)
        if ultimo is not None and hu_inicial <= ultimo and not self.chk_hu_usado.value:
            self._notificar(f"El HU {hu_inicial} ya fue usado (último: {ultimo}). Use {ultimo + 1}, marque "
                            "'Permitir un HU ya usado' o reimprima desde Reimpresión.", "#B91C1C")
            return
        try:
            df = EI.leer_oc_cencosud(self.archivo_oc_cencosud)
            resultado = EI.procesar_oc_cencosud(df, hu_inicial)
            if not resultado["etiquetas"]:
                self._notificar("La OC no tiene líneas con empaques pedidos.", "#D97706")
                return
        except Exception as ex:
            self._notificar(f"No se pudo procesar la OC: {ex}", "#B91C1C")
            return
        # Reservar los HU usados (el correlativo avanza; nunca retrocede)
        try:
            supabase.rpc("wms_reservar_correlativo", {"p_clave": "CENCOSUD_HU", "p_cantidad": resultado["hu_usados"],
                                                      "p_usuario": self._usuario_pc(), "p_desde": hu_inicial}).execute()
        except Exception as ex:
            self._notificar(f"No se pudo reservar el correlativo HU: {self._msg_error(ex)}", "#B91C1C")
            return
        # Guardar histórico (reemplaza Historico_Cencosud.xlsx)
        try:
            usuario = self._usuario_pc()
            filas = [{
                "numero_orden": f["Número de Orden"], "fecha_entrega": f["Fecha Entrega"], "hu": f["HU"],
                "cod_local": f["Cód. Local"], "nombre_local": f["Nombre Local"], "cod_cencosud": f["Cód. Cencosud"],
                "cod_proveedor": f["Cód. Proveedor"], "ean13": f["EAN13"], "descripcion": f["Descripción"],
                "empaques_pedidos": int(f["Empaques Pedidos"]), "unidades_empaque": int(f["Unidades por Empaque"]),
                "cantidad_total": int(f["Cantidad Total"]), "usuario": usuario, "origen": "WMS",
            } for f in resultado["imprimible"]]
            for i in range(0, len(filas), 500):
                supabase.table("wms_cencosud_hu").insert(filas[i:i + 500]).execute()
        except Exception as ex:
            self._notificar(f"Etiquetas generadas, pero no se guardó el histórico: {self._msg_error(ex)}", "#D97706")
        await self._emitir_zip_cencosud(resultado, (self.txt_factura_b2b.value or "").strip())
        self.txt_hu_inicial.value = ""
        self.chk_hu_usado.value = False
        self._cargar_estado_cencosud()
        self.page.update()

    async def _emitir_zip_cencosud(self, resultado: dict, factura: str = "", reimpresion: bool = False):
        try:
            marca = datetime.now().strftime("%Y%m%d_%H%M")
            oc = resultado.get("oc") or "OC"
            carpeta = Path(tempfile.gettempdir()) / "wms_cencosud" / f"OC_{oc}_{marca}"
            if carpeta.exists():
                shutil.rmtree(carpeta, ignore_errors=True)
            carpeta.mkdir(parents=True, exist_ok=True)
            rep = EI.reportes_cencosud(resultado, factura)
            EI.generar_pdf_etiquetas_cencosud(resultado["etiquetas"], str(carpeta / f"Etiquetas_OC_{oc}_{marca}.pdf"))
            EI.generar_excel_tabla([("Packing_List", rep["packing"]), ("Formato_B2B", rep["b2b"])],
                                   str(carpeta / f"Packing_List_OC_{oc}_{marca}.xlsx"))
            EI.generar_excel_tabla([("ORDEN-COMPRA", rep["conductor"])],
                                   str(carpeta / f"Imprimible_Conductor_OC_{oc}_{marca}.xlsx"))
            ruta_zip = shutil.make_archive(str(carpeta), "zip", root_dir=str(carpeta))
            destino = await self._descargar(ruta_zip, "Guardar etiquetas y reportes Cencosud", "zip")
            self.lbl_res_cencosud.value = (
                f"{'Descarga nuevamente' if reimpresion else 'Proceso finalizado'}: OC {oc} · {len(resultado['etiquetas'])} etiquetas · "
                f"{resultado['hu_usados']} HU ({resultado['hu_desde']} → {resultado['hu_hasta']}). "
                f"ZIP con etiquetas PDF, packing list y imprimible conductor. {destino}")
            self.lbl_res_cencosud.color = self.GREEN
            self.page.update()
            if not reimpresion:
                self._notificar(f"OC {oc}: {len(resultado['etiquetas'])} etiquetas. Siguiente HU: {resultado['hu_hasta'] + 1}.",
                                "#047857")
        except Exception as ex:
            self.lbl_res_cencosud.value = f"Error generando los archivos: {ex}"
            self.lbl_res_cencosud.color = self.RED
            self.page.update()
            registrar_error_pc("IMPRESION_CENCOSUD", f"{type(ex).__name__}: {ex}")

    async def _redescargar_oc(self, oc: str, hus: list):
        try:
            filas = (supabase.table("wms_cencosud_hu").select("*").eq("numero_orden", str(oc)).in_("hu", list(hus))
                     .order("id").execute().data or [])
        except Exception as ex:
            self._notificar(f"No se pudo leer el histórico: {self._msg_error(ex)}", "#B91C1C")
            return
        if not filas:
            self._notificar("No hay datos guardados de esa OC.", "#D97706")
            return
        await self._emitir_zip_cencosud(EI.resultado_desde_historico(filas), reimpresion=True)

    # ---------------- reimpresión de un HU ----------------
    def _buscar_hu_cencosud(self, e=None):
        hu = (self.txt_hu_reimp.value or "").strip()
        if not hu:
            self._notificar("Ingrese un número de HU.", "#D97706")
            return
        try:
            filas = supabase.table("wms_cencosud_hu").select("*").eq("hu", hu).order("id").execute().data or []
        except Exception as ex:
            self._notificar(f"No se pudo buscar: {self._msg_error(ex)}", "#B91C1C")
            return
        if not filas:
            self.dd_bultos_reimp.options, self.dd_bultos_reimp.disabled = [], True
            self.page.update()
            self._notificar(f"El HU {hu} no existe en el histórico. Si es antiguo, importe Historico_Cencosud.xlsx.", "#D97706")
            return
        # Si el HU se procesó más de una vez, usar el último proceso
        ultimo_proceso = max(str(f.get("fecha_proceso") or "")[:16] for f in filas)
        filas = [f for f in filas if str(f.get("fecha_proceso") or "")[:16] == ultimo_proceso]
        self.filas_reimp = filas
        opciones, _ = EI.etiquetas_desde_historico(filas, hu)
        self.dd_bultos_reimp.options = ([self._opcion("TODOS", "IMPRIMIR TODOS LOS BULTOS DEL HU")]
                                        + [self._opcion(o, o) for o in opciones])
        self.dd_bultos_reimp.value = "TODOS"
        self.dd_bultos_reimp.disabled = False
        self.page.update()
        self._notificar(f"HU {hu}: {len(opciones)} bultos (local {filas[0].get('cod_local')}, OC {filas[0].get('numero_orden')}).",
                        "#047857")

    async def _reimprimir_hu_cencosud(self, e=None):
        hu = (self.txt_hu_reimp.value or "").strip()
        if not self.filas_reimp or not hu:
            self._notificar("Busque primero el HU.", "#D97706")
            return
        _, etiquetas = EI.etiquetas_desde_historico(self.filas_reimp, hu, self.dd_bultos_reimp.value or "TODOS")
        if not etiquetas:
            self._notificar("No se pudo armar la etiqueta seleccionada.", "#B91C1C")
            return
        try:
            carpeta = Path(tempfile.gettempdir()) / "wms_cencosud"
            carpeta.mkdir(parents=True, exist_ok=True)
            ruta = carpeta / f"Reimpresion_HU_{hu}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            EI.generar_pdf_etiquetas_cencosud(etiquetas, str(ruta))
            destino = await self._descargar(str(ruta), "Guardar reimpresión", "pdf")
            self._notificar(f"Reimpresión lista: {len(etiquetas)} etiqueta(s). {destino}", "#047857")
        except Exception as ex:
            self._notificar(f"Error en la reimpresión: {ex}", "#B91C1C")

    # ---------------- importar el histórico Excel de la app antigua ----------------
    async def _elegir_historico_antiguo(self, e=None):
        try:
            ruta = await self._elegir_archivo(["xlsx"])
        except Exception as ex:
            self._notificar(f"No se pudo abrir el selector: {ex}", "#B91C1C")
            return
        if not ruta:
            return
        try:
            import pandas as pd
            df = pd.read_excel(ruta, dtype=str).fillna("")
            if "HU" not in df.columns:
                raise RuntimeError("el archivo no tiene la columna HU")
            existentes = set()
            for i in range(0, 100000, 1000):
                lote = (supabase.table("wms_cencosud_hu").select("numero_orden, hu, cod_local, ean13, empaques_pedidos")
                        .range(i, i + 999).execute().data or [])
                existentes |= {(str(x["numero_orden"]), str(x["hu"]), str(x["cod_local"]), str(x["ean13"]),
                                int(x["empaques_pedidos"] or 0)) for x in lote}
                if len(lote) < 1000:
                    break

            def entero(v, defecto=0):
                try:
                    return int(float(str(v).strip() or defecto))
                except ValueError:
                    return defecto

            nuevas = []
            for _, r in df.iterrows():
                fila = {
                    "numero_orden": str(r.get("Número de Orden", "")).strip(), "fecha_entrega": str(r.get("Fecha Entrega", "")).strip(),
                    "hu": str(r.get("HU", "")).strip(), "cod_local": str(r.get("Cód. Local", "")).strip(),
                    "nombre_local": str(r.get("Nombre Local", "")).strip(), "cod_cencosud": str(r.get("Cód. Cencosud", "")).strip(),
                    "cod_proveedor": str(r.get("Cód. Proveedor", "")).strip(), "ean13": str(r.get("EAN13", "")).strip(),
                    "descripcion": str(r.get("Descripción", "")).strip(),
                    "empaques_pedidos": entero(r.get("Empaques Pedidos", 0)), "unidades_empaque": entero(r.get("Unidades por Empaque", 1), 1),
                    "cantidad_total": entero(r.get("Cantidad Total", 0)), "usuario": self._usuario_pc(), "origen": "IMPORTADO",
                }
                try:   # conservar la fecha de proceso original (dd/mm/aaaa hh:mm:ss)
                    fp = pd.to_datetime(str(r.get("Fecha Proceso", "")).strip(), dayfirst=True)
                    if not pd.isna(fp):
                        fila["fecha_proceso"] = fp.strftime("%Y-%m-%dT%H:%M:%S") + "-03:00"
                except Exception:
                    pass
                if not fila["hu"] or not fila["numero_orden"]:
                    continue
                clave = (fila["numero_orden"], fila["hu"], fila["cod_local"], fila["ean13"], fila["empaques_pedidos"])
                if clave in existentes:
                    continue
                existentes.add(clave)
                nuevas.append(fila)
            for i in range(0, len(nuevas), 500):
                supabase.table("wms_cencosud_hu").insert(nuevas[i:i + 500]).execute()
            self._notificar(f"Histórico importado: {len(nuevas)} líneas nuevas ({len(df) - len(nuevas)} ya existían o vacías).",
                            "#047857")
            self._cargar_estado_cencosud()
            self.page.update()
        except Exception as ex:
            self._notificar(f"No se pudo importar el histórico: {ex}", "#B91C1C")
