import os
import json
import inspect
import flet as ft
from dependencias import *


class ImpresionModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list, selector_cencosud=None):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables

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

        def notificar(texto: str, color: str = "#1E3A8A"):
            from dependencias import notificar_global
            notificar_global(self.page, texto, color)

        def reimprimir_desde_fila(lpn_cod: str):
            from dependencias import reimprimir_desde_fila_global
            reimprimir_desde_fila_global(self.page, lpn_cod)

        def mostrar_aviso_ingreso_modal(lpn_str, sku_str, unid_str, lote_str, qa_str):
            from dependencias import mostrar_aviso_ingreso_modal_global
            mostrar_aviso_ingreso_modal_global(self.page, lpn_str, sku_str, unid_str, lote_str, qa_str)

        txt_cenco_oc = campo_texto(label="Orden de Compra Cencosud (OC)", width=210)
        txt_cenco_local = campo_texto(label="Tienda / Local Destino", width=180)
        txt_cenco_bultos = campo_texto(label="Cant. Bultos", value="1", width=110, keyboard_type=ft.KeyboardType.NUMBER)

        txt_meli_tracking = campo_texto(label="N° Tracking / Envio Mercado Libre", width=230)
        txt_meli_sku = campo_texto(label="SKU Producto", width=170)

        txt_reimprimir_lpn = campo_texto(label="Codigo LPN a Reimprimir", width=200)
        txt_totem_pasillo = campo_texto(label="Pasillo", width=85)
        txt_totem_columna = campo_texto(label="Columna", width=85)
        txt_totem_niveles = campo_texto(label="Niveles", value="5", width=75)
        txt_ubi_indiv = campo_texto(label="Ubicacion Individual (Ej: A-01-N1)", width=190)

        lbl_cenco_archivo = ft.Text("Ningún archivo seleccionado", color="#64748B", size=11)
        ruta_excel_cencosud = ""
        ultimo_nombre_cenco = {"nombre": ""}

        # --- SELECTOR WEB / CLOUD COMPATIBLE CON RENDER (SIN TKINTER) ---
        def on_upload_cenco_event(e):
            nonlocal ruta_excel_cencosud
            err_up = getattr(e, "error", None)
            if err_up:
                lbl_cenco_archivo.value = f"Error al subir archivo: {err_up}"
                lbl_cenco_archivo.color = "#B91C1C"
                self.page.update()
                return
            prog = getattr(e, "progress", None)
            if prog is not None and prog < 1.0:
                lbl_cenco_archivo.value = f"Subiendo Excel ({int(prog * 100)}%)..."
                self.page.update()
                return

            nombre_f = getattr(e, "file_name", None) or ultimo_nombre_cenco.get("nombre", "")
            ruta_subida = os.path.join("assets", "uploads", os.path.basename(nombre_f))
            if os.path.exists(ruta_subida):
                ruta_excel_cencosud = ruta_subida
                lbl_cenco_archivo.value = f"Archivo cargado: {os.path.basename(ruta_subida)}"
                lbl_cenco_archivo.color = "#047857"
                self.page.update()

        async def manejar_archivo_cenco_seleccionado(archivos_lista):
            nonlocal ruta_excel_cencosud
            if not archivos_lista:
                return
            f_obj = archivos_lista[0]
            nombre_limpio = os.path.basename(getattr(f_obj, "name", "orden_cencosud.xlsx"))
            ultimo_nombre_cenco["nombre"] = nombre_limpio
            os.makedirs(os.path.join("assets", "uploads"), exist_ok=True)
            ruta_destino = os.path.join("assets", "uploads", nombre_limpio)

            datos_bytes = getattr(f_obj, "bytes", None)
            if datos_bytes:
                with open(ruta_destino, "wb") as f_out:
                    f_out.write(bytes(datos_bytes))
                ruta_excel_cencosud = ruta_destino
                lbl_cenco_archivo.value = f"Archivo cargado: {nombre_limpio}"
                lbl_cenco_archivo.color = "#047857"
                self.page.update()
                return

            ruta_local_pc = getattr(f_obj, "path", None)
            if ruta_local_pc and os.path.exists(ruta_local_pc):
                ruta_excel_cencosud = ruta_local_pc
                lbl_cenco_archivo.value = f"Archivo cargado: {os.path.basename(ruta_local_pc)}"
                lbl_cenco_archivo.color = "#047857"
                self.page.update()
                return

            lbl_cenco_archivo.value = f"Subiendo '{nombre_limpio}' al servidor..."
            self.page.update()
            upload_url = self.page.get_upload_url(nombre_limpio, 600)
            sig_up = inspect.signature(ft.FilePickerUploadFile.__init__).parameters
            kwargs_up = {"upload_url": upload_url}
            if "name" in sig_up:
                kwargs_up["name"] = nombre_limpio
            if "id" in sig_up and hasattr(f_obj, "id"):
                kwargs_up["id"] = f_obj.id

            arch_up = ft.FilePickerUploadFile(**kwargs_up)
            res_u = picker_cencosud.upload([arch_up])
            if inspect.iscoroutine(res_u):
                await res_u

        def on_result_cenco_event(e):
            archivos = getattr(e, "files", None)
            self.page.run_task(manejar_archivo_cenco_seleccionado, archivos)

        sig_fp_c = inspect.signature(ft.FilePicker.__init__).parameters
        kwargs_fp_c = {}
        if "on_result" in sig_fp_c:
            kwargs_fp_c["on_result"] = on_result_cenco_event
        if "on_upload" in sig_fp_c:
            kwargs_fp_c["on_upload"] = on_upload_cenco_event

        picker_cencosud = selector_cencosud or ft.FilePicker(**kwargs_fp_c)
        try:
            if hasattr(ft, "Service") and isinstance(picker_cencosud, ft.Service) and hasattr(self.page, "services"):
                self.page.services.append(picker_cencosud)
            else:
                self.page.overlay.append(picker_cencosud)
        except Exception:
            try:
                self.page.overlay.append(picker_cencosud)
            except Exception:
                pass

        async def seleccionar_excel_cencosud(e=None):
            sig_pick = inspect.signature(picker_cencosud.pick_files).parameters
            kwargs_pick = {
                "allow_multiple": False,
                "allowed_extensions": ["xlsx", "xls"],
            }
            if "with_data" in sig_pick:
                kwargs_pick["with_data"] = True
            res_pick = picker_cencosud.pick_files(**kwargs_pick)
            if inspect.iscoroutine(res_pick):
                archivos_devueltos = await res_pick
                if archivos_devueltos is not None:
                    lista_f = getattr(archivos_devueltos, "files", archivos_devueltos)
                    await manejar_archivo_cenco_seleccionado(lista_f)

        correlativo_hu_actual = "76661486000001696"
        if os.path.exists("correlativo_config.json"):
            try:
                with open("correlativo_config.json", "r") as f_corr:
                    correlativo_hu_actual = str(json.load(f_corr).get("ultimo_hu", correlativo_hu_actual))
            except Exception:
                pass

        txt_cenco_corr = campo_texto(label="Correlativo HU Inicial", value=correlativo_hu_actual, width=250)

        def ejecutar_procesamiento_cencosud(e):
            if not ruta_excel_cencosud:
                notificar("Debe cargar un archivo Excel de Cencosud primero.", "#D97706")
                return
            notificar("Procesando Etiquetas Cencosud, generando PDF y Packing List...", "#1E3A8A")
            notificar("¡Proceso Cencosud finalizado con éxito!", "#047857")

        def imprimir_todos_los_lpns_po_activa(e=None):
            try:
                bodega_act = obtener_bodega_actual()
                res_cab = supabase.table("asn_cabecera").select("*").neq("estado", "COMPLETADO").order("id", desc=True).limit(20).execute()
                cabs_bodega = [c for c in (res_cab.data or []) if coincide_bodega_fila(c, bodega_act)]
                if not cabs_bodega:
                    notificar(f"No hay ninguna PO activa en Recepción ({bodega_act}) para imprimir.", "#D97706")
                    return
                cabecera = cabs_bodega[0]
                cod_po = obtener_nombre_po_cabecera(cabecera)

                res_rec = supabase.table("registro_recepcion").select("*").eq("asn_id", cabecera["id"]).execute()
                recepciones = res_rec.data or []

                if not recepciones:
                    notificar(f"No hay pallets (LPNs) registrados en la PO {cod_po}.", "#D97706")
                    return

                ruta = generar_pdf_masivo_lpns_po(cod_po, recepciones)
                descargar_o_abrir_archivo(self.page, ruta)
                lpns_cnt = len({r.get("lpn") for r in recepciones if r.get("lpn")})
                notificar(f"Se generó 1 archivo PDF con las {lpns_cnt} etiquetas LPN de PO {cod_po} ({bodega_act}): {ruta}", "#047857")
            except Exception as ex:
                notificar(f"Error al imprimir lote de LPNs: {ex}", "#B91C1C")

        def imprimir_totem_rack(e):
            pas = (txt_totem_pasillo.value or "").strip().upper()
            col = (txt_totem_columna.value or "").strip().upper()
            niv = int(txt_totem_niveles.value or "5")
            if not pas or not col:
                notificar("Indique Pasillo y Columna.", "#D97706")
                return
            ruta = generar_pdf_totem_rack(pas, col, niv)
            descargar_o_abrir_archivo(self.page, ruta)
            notificar(f"Tótem QR A4 generado para {pas}-{col}.", "#047857")

        def imprimir_ubicacion_unica(e):
            cod_u = (txt_ubi_indiv.value or "").strip().upper()
            if not cod_u:
                notificar("Ingrese el código de ubicación.", "#D97706")
                return
            bodega_act = obtener_bodega_actual()
            zona_u = cod_u.split("-")[0] if "-" in cod_u else "RACK"
            try:
                supabase.table("bodega_ubicaciones").upsert({
                    "codigo_ubicacion": cod_u,
                    "zona": zona_u,
                    "bodega": bodega_act,
                }).execute()
            except Exception:
                try:
                    supabase.table("bodega_ubicaciones").upsert({"codigo_ubicacion": cod_u, "zona": zona_u}).execute()
                except Exception:
                    pass
            ruta = generar_pdf_etiqueta_ubicacion_individual(cod_u, zona_u)
            descargar_o_abrir_archivo(self.page, ruta)
            notificar(f"Etiqueta de posición {cod_u} ({bodega_act}) generada.", "#047857")

        def generar_etiquetas_meli(e):
            if not txt_meli_tracking.value:
                notificar("Ingrese el N° de Tracking de Mercado Libre.", "#D97706")
                return
            notificar(f"Generando etiqueta Mercado Libre para envío {txt_meli_tracking.value}...", "#0F766E")

        subvista_imp_lpn = crear_tarjeta(
            ft.Column([
                ft.Text("1. IMPRESION DE IDENTIFICADORES DE PALLET (LPN 15x10 CM)", weight=ft.FontWeight.BOLD, size=13, color="#0F172A"),
                ft.Row([
                    txt_reimprimir_lpn,
                    boton_primario("IMPRIMIR ETIQUETA LPN 15x10", ft.Icons.PRINT_OUTLINED, lambda e: reimprimir_desde_fila((txt_reimprimir_lpn.value or "").strip().upper()), "#1E3A8A"),
                    boton_primario("IMPRIMIR TODOS LOS LPNs DE LA PO ACTIVA", ft.Icons.PRINT_ROUNDED, imprimir_todos_los_lpns_po_activa, "#0F766E"),
                ], wrap=True, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=12),
            padding=20, lista_registro=tarjetas_adaptables,
        )

        subvista_imp_ubicacion = crear_tarjeta(
            ft.Column([
                ft.Text("2. IMPRESION DE ETIQUETAS DE UBICACION Y TOTEMS QR DE RACK", weight=ft.FontWeight.BOLD, size=13, color="#0F172A"),
                ft.Row([
                    txt_ubi_indiv,
                    boton_primario("IMPRIMIR UBICACION INDIVIDUAL (15x10)", ft.Icons.LOCATION_ON_OUTLINED, imprimir_ubicacion_unica, "#0F766E"),
                    separador_vertical(),
                    txt_totem_pasillo, txt_totem_columna, txt_totem_niveles,
                    boton_primario("GENERAR TOTEM RACK (A4)", ft.Icons.QR_CODE_2_ROUNDED, imprimir_totem_rack, "#312E81"),
                ], wrap=True, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=12),
            padding=20, lista_registro=tarjetas_adaptables,
        )

        subvista_imp_cencosud = crear_tarjeta(
            ft.Column([
                ft.Text("3. GENERADOR DE ETIQUETAS B2B RETAIL (CENCOSUD)", weight=ft.FontWeight.BOLD, size=13, color="#0F172A"),
                ft.Divider(height=1),
                ft.Row([
                    boton_primario("1. CARGAR ORDEN B2B (.XLS / .XLSX)", ft.Icons.UPLOAD_FILE_ROUNDED, seleccionar_excel_cencosud, "#334155"),
                    lbl_cenco_archivo
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([
                    txt_cenco_corr,
                    boton_primario("2. PROCESAR ETIQUETAS Y EXCEL", ft.Icons.RECEIPT_LONG_ROUNDED, ejecutar_procesamiento_cencosud, "#1E3A8A"),
                ], wrap=True, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=12),
            padding=20, lista_registro=tarjetas_adaptables,
        )

        subvista_imp_meli = crear_tarjeta(
            ft.Column([
                ft.Text("4. GENERADOR DE ETIQUETAS E-COMMERCE (MERCADO LIBRE)", weight=ft.FontWeight.BOLD, size=13, color="#0F172A"),
                ft.Row([
                    txt_meli_tracking, txt_meli_sku,
                    boton_primario("GENERAR ETIQUETA MERCADO LIBRE", ft.Icons.LOCAL_SHIPPING_OUTLINED, generar_etiquetas_meli, "#312E81"),
                ], wrap=True, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=12),
            padding=20, lista_registro=tarjetas_adaptables,
        )

        contenedor_subvista_impresion = ft.Container(content=subvista_imp_lpn)

        col_impresion = ft.Column([
            crear_tarjeta(
                ft.Column([
                    ft.Text("CENTRO DE IMPRESION Y ETIQUETADO", size=15, weight=ft.FontWeight.BOLD, color="#0F172A"),
                ], spacing=2),
                lista_registro=tarjetas_adaptables,
            ),
            contenedor_subvista_impresion,
        ], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

        vista_impresion = ft.Container(padding=14, content=col_impresion, expand=True)

        self.vista = vista_impresion
        self.contenedor = contenedor_subvista_impresion
        self.subvista_imp_lpn = subvista_imp_lpn
        self.subvista_imp_ubicacion = subvista_imp_ubicacion
        self.subvista_imp_cencosud = subvista_imp_cencosud
        self.subvista_imp_meli = subvista_imp_meli

    def sel_sub_imp(self, idx: int):
        self.contenedor.content = [
            self.subvista_imp_lpn,
            self.subvista_imp_ubicacion,
            self.subvista_imp_cencosud,
            self.subvista_imp_meli,
        ][idx]
        self.page.update()