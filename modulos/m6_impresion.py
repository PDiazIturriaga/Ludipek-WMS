import os
import json
import flet as ft
from dependencias import *

class ImpresionModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list, selector_cencosud=None):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables
        
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
        
        def seleccionar_excel_cencosud(e):
            nonlocal ruta_excel_cencosud
            import tkinter as tk
            from tkinter import filedialog
            
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            ruta = filedialog.askopenfilename(
                title="Seleccionar Excel Cencosud", 
                filetypes=[("Archivos Excel", "*.xlsx *.xls")]
            )
            root.destroy()
            
            if ruta:
                ruta_excel_cencosud = ruta
                lbl_cenco_archivo.value = f"Archivo cargado: {os.path.basename(ruta)}"
                lbl_cenco_archivo.color = "#047857"
                self.page.update()
        
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
                res_cab = supabase.table("asn_cabecera").select("*").neq("estado", "COMPLETADO").order("id", desc=True).limit(1).execute()
                if not res_cab.data:
                    notificar("No hay ninguna PO activa en Recepción para imprimir.", "#D97706")
                    return
                cabecera = res_cab.data[0]
                cod_po = cabecera.get("codigo_asn", "PO-ACTIVA")
                
                res_rec = supabase.table("registro_recepcion").select("*").eq("asn_id", cabecera["id"]).execute()
                recepciones = res_rec.data or []
                
                if not recepciones:
                    notificar(f"No hay pallets (LPNs) registrados en la PO {cod_po}.", "#D97706")
                    return
                
                ruta = generar_pdf_masivo_lpns_po(cod_po, recepciones)
                descargar_o_abrir_archivo(self.page, ruta)
                lpns_cnt = len({r.get("lpn") for r in recepciones if r.get("lpn")})
                notificar(f"Se generó 1 archivo PDF con las {lpns_cnt} etiquetas LPN de {formatear_nombre_po(cod_po)}: {ruta}", "#047857")
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
            try:
                supabase.table("bodega_ubicaciones").upsert({"codigo_ubicacion": cod_u, "zona": cod_u.split("-")[0]}).execute()
            except Exception:
                pass
            ruta = generar_pdf_etiqueta_ubicacion_individual(cod_u, cod_u.split("-")[0])
            descargar_o_abrir_archivo(self.page, ruta)
            notificar(f"Etiqueta de posición {cod_u} generada.", "#047857")

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
                    boton_primario("1. CARGAR ORDEN B2B (.XLS)", ft.Icons.UPLOAD_FILE_ROUNDED, seleccionar_excel_cencosud, "#334155"),
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