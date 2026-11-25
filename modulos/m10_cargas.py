import os
from datetime import datetime
import pandas as pd
import flet as ft
from dependencias import *


# =====================================================================
# CARGAS DE CAMIÓN (script 40)
# 1) OT por cargar: OT pickeadas (LISTA_PARA_CARGA) con sus pallets, cajas y fotos de la fecha.
#    Ajustes antes de cargar: cambiar lote/fecha, mover cajas de pallet, reabrir a picking.
#    Las fotos son un registro interno de Santiago (Concepción no las ve).
# 2) Cargas de camión: patente/contenedor, OT u OV ancladas y pallets/bultos 1/10, 2/10...
#    Al cerrar la carga la OT sale de Santiago (EN_TRANSITO_CCP). Las OV solo quedan registradas.
# =====================================================================

COLOR_ITEM = {"CARGADO": "#10B981", "PENDIENTE": "#F59E0B", "QUITADO": "#64748B"}
NOMBRE_ITEM = {"CARGADO": "Cargado", "PENDIENTE": "Por subir", "QUITADO": "Otro camión"}
COLOR_CARGA = {"ABIERTA": "#38BDF8", "CERRADA": "#10B981", "ANULADA": "#64748B"}


def _fh(valor) -> str:
    return formatear_fecha_hora_chile(valor) if valor else "—"


def _n(valor) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _miles(valor) -> str:
    return f"{_n(valor):,}".replace(",", ".")


def _error(ex) -> str:
    msg = getattr(ex, "message", None) or str(ex)
    if isinstance(msg, dict):
        msg = msg.get("message") or str(msg)
    msg = str(msg)
    if "PGRST202" in msg or ("wms_carga" in msg and "Could not find" in msg) or ("wms_ot_por_cargar" in msg and "Could not find" in msg):
        return "falta ejecutar 40_cargas_camion.sql en Supabase"
    return msg.replace("WMS: ", "", 1)


def _chip(texto: str, color: str):
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.16, color),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.5, color)),
        content=ft.Text(texto, size=11, weight=ft.FontWeight.W_600, color=color),
    )


def _campo(label: str, width: int = 300, **kw):
    return ft.TextField(label=label, dense=True, width=width, bgcolor=UI["input"], color=UI["texto"],
                        border_color=UI["borde"], focused_border_color=UI["acento"], border_radius=6,
                        text_style=ft.TextStyle(size=12), **kw)


class CargasCamionModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables
        self.vista_actual = 0          # 0 = OT por cargar · 1 = cargas de camión
        self.ots = []                  # wms_ot_por_cargar
        self.ot = None                 # OT abierta en el detalle
        self.cajas = []                # wms_ot_cajas_detalle de la OT abierta
        self.sel_cajas = set()         # ids de cajas elegidas
        self.cargas = []               # wms_cargas_lista
        self.carga = None              # wms_carga_detalle abierta

        # ---------------- Indicadores ----------------
        self.k_ots = ft.Text("0")
        self.k_ots_det = ft.Text("", size=11, color=UI["texto_3"])
        self.k_abiertas = ft.Text("0")
        self.k_por_subir = ft.Text("0")
        self.k_cerradas = ft.Text("0")
        self.k_cerradas_det = ft.Text("últimos 15 días", size=11, color=UI["texto_3"])
        fila_kpis = ft.ResponsiveRow([
            ui_kpi(self.k_ots, "OT listas para carga", ft.Icons.INVENTORY_2_OUTLINED, UI["acento"], self.k_ots_det),
            ui_kpi(self.k_abiertas, "Cargas abiertas", ft.Icons.LOCAL_SHIPPING_OUTLINED, UI["primario"]),
            ui_kpi(self.k_por_subir, "Pallets / bultos por subir", ft.Icons.UPLOAD_ROUNDED, UI["alerta"]),
            ui_kpi(self.k_cerradas, "Cargas cerradas", ft.Icons.VERIFIED_ROUNDED, UI["exito"], self.k_cerradas_det),
        ], spacing=12, run_spacing=12)

        # ---------------- OT por cargar ----------------
        self.tabla_ots = ft.DataTable(
            heading_row_height=38, data_row_min_height=44, data_row_max_height=56,
            columns=[ft.DataColumn(ft.Text(t, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"]), numeric=num)
                     for t, num in [("OT", False), ("Estado", False), ("Pallets", True), ("Unidades", True),
                                    ("Cajas con foto", True), ("Pickeada", False), ("En carga", False)]],
            rows=[],
        )
        self.txt_vacio_ots = ft.Text("No hay OT pickeadas esperando camión.", size=12.5, color=UI["texto_2"], visible=False)
        self.sub_ots = ft.Column([
            ui_tarjeta(ft.Column([ui_tabla(self.tabla_ots, 420), self.txt_vacio_ots], spacing=8, tight=True),
                       titulo="OT pickeadas en Santiago, esperando camión",
                       subtitulo="Haga clic en una OT para ver sus cajas con foto y ajustarla antes de cargar",
                       icono=ft.Icons.INVENTORY_2_OUTLINED),
        ], spacing=14, tight=True)

        # ---------------- Detalle de una OT ----------------
        self.lbl_ot = ft.Text("", size=20, weight=ft.FontWeight.W_700, color=UI["texto"])
        self.chip_ot = ft.Container()
        self.lbl_ot_meta = ft.Text("", size=12, color=UI["texto_2"])
        self.lbl_sel = ft.Text("Ninguna caja elegida", size=12, color=UI["texto_2"])
        self.fila_pallets = ft.ResponsiveRow(spacing=10, run_spacing=10)
        self.tabla_cajas = ft.DataTable(
            show_checkbox_column=True,
            heading_row_height=38, data_row_min_height=40, data_row_max_height=48,
            columns=[ft.DataColumn(ft.Text(t, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"]), numeric=num)
                     for t, num in [("Pallet", False), ("SKU", False), ("Descripción", False), ("Lote", False),
                                    ("Vence", False), ("Fecha leída", False), ("UN", True), ("Ubicación", False),
                                    ("Pickeó", False), ("Foto", False)]],
            rows=[],
        )
        self.btn_reabrir = ui_boton("Reabrir a picking", ft.Icons.UNDO_ROUNDED, lambda e: self._dialogo_reabrir(), "peligro",
                                    tooltip="Devuelve la OT al picking del celular para agregar o quitar cajas")
        self.sub_ot = ft.Column([
            ft.Container(
                padding=16, border_radius=10, bgcolor=UI["card"], border=ft.Border.all(1, UI["borde"]),
                content=ft.Row([
                    ft.IconButton(icon=ft.Icons.ARROW_BACK_ROUNDED, icon_color=UI["acento"], tooltip="Volver",
                                  on_click=lambda e: self.sel_sub_cargas(0)),
                    ft.Column([ft.Row([self.lbl_ot, self.chip_ot], spacing=12, wrap=True), self.lbl_ot_meta],
                              spacing=4, tight=True, expand=True),
                    ft.Row([
                        ui_boton("Fotos de la fecha", ft.Icons.PHOTO_LIBRARY_OUTLINED, lambda e: self._dialogo_fotos(), "secundario",
                                 tooltip="Registro interno de Santiago: foto de la fecha de cada caja"),
                        ui_boton("Historial de ajustes", ft.Icons.HISTORY_ROUNDED, lambda e: self._dialogo_historial(), "secundario"),
                        self.btn_reabrir,
                    ], spacing=8, wrap=True),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ),
            ui_tarjeta(self.fila_pallets, titulo="Pallets por cargar", icono=ft.Icons.VIEW_IN_AR_OUTLINED),
            ui_tarjeta(ui_tabla(self.tabla_cajas, 420), titulo="Cajas pickeadas",
                       subtitulo="Marque las cajas y elija qué hacer con ellas",
                       icono=ft.Icons.FACT_CHECK_OUTLINED,
                       acciones=[self.lbl_sel,
                                 ui_boton("Cambiar lote / fecha", ft.Icons.EDIT_CALENDAR_ROUNDED, lambda e: self._dialogo_lote(), "secundario"),
                                 ui_boton("Mover a otro pallet", ft.Icons.MOVE_UP_ROUNDED, lambda e: self._dialogo_mover(), "secundario")]),
        ], spacing=14, tight=True)

        # ---------------- Cargas de camión ----------------
        self.tabla_cargas = ft.DataTable(
            heading_row_height=38, data_row_min_height=44, data_row_max_height=56,
            columns=[ft.DataColumn(ft.Text(t, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"]), numeric=num)
                     for t, num in [("Carga", False), ("Patente", False), ("Contenedor", False), ("Destino", False),
                                    ("OT / OV", False), ("Cargados", True), ("Estado", False), ("Creada", False), ("Cerrada", False)]],
            rows=[],
        )
        self.txt_vacio_cargas = ft.Text("No hay cargas en los últimos 15 días.", size=12.5, color=UI["texto_2"], visible=False)
        self.sub_cargas = ft.Column([
            ui_tarjeta(ft.Column([ui_tabla(self.tabla_cargas, 420), self.txt_vacio_cargas], spacing=8, tight=True),
                       titulo="Cargas de camión",
                       subtitulo="Se arman en el celular (Carga de camión) o aquí. Haga clic para ver pallet por pallet.",
                       icono=ft.Icons.LOCAL_SHIPPING_OUTLINED,
                       acciones=[ui_boton("Nueva carga", ft.Icons.ADD_ROUNDED, lambda e: self._dialogo_nueva_carga())]),
        ], spacing=14, tight=True)

        # ---------------- Detalle de una carga ----------------
        self.lbl_carga = ft.Text("", size=20, weight=ft.FontWeight.W_700, color=UI["texto"])
        self.chip_carga = ft.Container()
        self.lbl_carga_meta = ft.Text("", size=12, color=UI["texto_2"])
        self.barra_carga = ft.ProgressBar(value=0, color=UI["exito"], bgcolor=UI["borde"], height=8)
        self.txt_agregar = _campo("Agregar OT u OV", 220, on_submit=lambda e: self._agregar_orden())
        self.txt_scan = _campo("Escanear / escribir LPN o bulto", 260, on_submit=lambda e: self._marcar_cargado())
        self.fila_acciones_carga = ft.Row([], spacing=8, wrap=True)
        self.tabla_items = ft.DataTable(
            heading_row_height=38, data_row_min_height=40, data_row_max_height=52,
            columns=[ft.DataColumn(ft.Text(t, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"]), numeric=num)
                     for t, num in [("Orden", False), ("Pallet / bulto", False), ("Código", False), ("Cajas", True),
                                    ("UN", True), ("Estado", False), ("Quién / cuándo", False), ("Motivo", False), ("", False)]],
            rows=[],
        )
        self.sub_carga = ft.Column([
            ft.Container(
                padding=16, border_radius=10, bgcolor=UI["card"], border=ft.Border.all(1, UI["borde"]),
                content=ft.Column([
                    ft.Row([
                        ft.IconButton(icon=ft.Icons.ARROW_BACK_ROUNDED, icon_color=UI["acento"], tooltip="Volver",
                                      on_click=lambda e: self.sel_sub_cargas(1)),
                        ft.Column([ft.Row([self.lbl_carga, self.chip_carga], spacing=12, wrap=True), self.lbl_carga_meta],
                                  spacing=4, tight=True, expand=True),
                        self.fila_acciones_carga,
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    self.barra_carga,
                ], spacing=10, tight=True),
            ),
            ui_tarjeta(ui_tabla(self.tabla_items, 460), titulo="Pallets y bultos", icono=ft.Icons.VIEW_LIST_ROUNDED),
        ], spacing=14, tight=True)

        self.contenedor = ft.Container(content=self.sub_ots)
        self.vista = ft.Container(
            padding=16, bgcolor=UI["bg"], expand=True,
            content=ft.Column([
                ui_encabezado(
                    "Cargas de camión",
                    "OT listas para carga, ajustes antes de cargar y camiones pallet por pallet",
                    ft.Icons.LOCAL_SHIPPING_OUTLINED,
                    [ui_boton("Actualizar", ft.Icons.REFRESH_ROUNDED, lambda e: self.refrescar(), "secundario")],
                ),
                fila_kpis,
                self.contenedor,
            ], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True),
        )

    # ==================================================================
    # Utilidades
    # ==================================================================
    def _notificar(self, texto: str, color: str = "#1E3A8A"):
        notificar_global(self.page, texto, color)

    def _usuario(self) -> str:
        return str(getattr(self.page, "usuario_actual", None) or "PC")

    def _bodega(self) -> str:
        return obtener_bodega_activa(self.page)

    def _rpc(self, nombre: str, params: dict):
        return supabase.rpc(nombre, params).execute().data

    def _cerrar_dialogo(self, e=None):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def _dialogo(self, titulo: str, contenido, acciones: list, ancho: int = 460):
        self.page.show_dialog(ft.AlertDialog(
            bgcolor=UI["card"],
            title=ft.Text(titulo, size=18, weight=ft.FontWeight.W_700, color=UI["texto"]),
            content=ft.Container(width=ancho, content=contenido),
            actions=acciones, actions_alignment=ft.MainAxisAlignment.END))

    # ==================================================================
    # Datos generales
    # ==================================================================
    def cargar_todo(self, forzar: bool = False):
        # Al abrir el módulo el portal llama a sel_sub y a refrescar seguidos: no leer dos veces
        ahora = datetime.now().timestamp()
        clave = self._bodega()
        if not forzar and getattr(self, "_ultima_lectura", None) == clave and ahora - getattr(self, "_t_lectura", 0) < 1.5:
            return
        self._ultima_lectura, self._t_lectura = clave, ahora
        try:
            self.ots = list(self._rpc("wms_ot_por_cargar", {"p_bodega": self._bodega()}) or [])
        except Exception as ex:
            self.ots = []
            self._notificar(f"No se pudieron leer las OT por cargar: {_error(ex)}", "#B91C1C")
        try:
            self.cargas = list(self._rpc("wms_cargas_lista", {"p_bodega": self._bodega(), "p_solo_abiertas": False,
                                                               "p_dias": 15}) or [])
        except Exception as ex:
            self.cargas = []
            self._notificar(f"No se pudieron leer las cargas: {_error(ex)}", "#B91C1C")
        self.k_ots.value = str(len(self.ots))
        self.k_ots_det.value = f"{sum(len(o.get('pallets') or []) for o in self.ots)} pallets en bodega"
        abiertas = [c for c in self.cargas if c.get("estado") == "ABIERTA"]
        self.k_abiertas.value = str(len(abiertas))
        self.k_por_subir.value = str(sum(_n(c.get("total")) - _n(c.get("cargados")) for c in abiertas))
        self.k_cerradas.value = str(sum(1 for c in self.cargas if c.get("estado") == "CERRADA"))
        self._pintar_ots()
        self._pintar_cargas()

    # ==================================================================
    # OT por cargar
    # ==================================================================
    def _pintar_ots(self):
        filas = []
        for o in self.ots:
            pallets = o.get("pallets") or []
            en_carga = sorted({p.get("carga") for p in pallets if p.get("carga")})
            filas.append(ft.DataRow(
                on_select_change=lambda e, oid=o.get("orden_id"): self.abrir_ot(oid),
                cells=[
                    ft.DataCell(ft.Text(str(o.get("numero_ov") or ""), size=13, weight=ft.FontWeight.W_700, color=UI["acento"])),
                    ft.DataCell(_chip("Quedan pallets" if o.get("parcial") else "Lista para carga",
                                      UI["alerta"] if o.get("parcial") else "#A78BFA")),
                    ft.DataCell(ft.Text(str(len(pallets)), size=12.5, color=UI["texto"])),
                    ft.DataCell(ft.Text(_miles(sum(_n(p.get("unidades")) for p in pallets)), size=12.5, color=UI["texto"])),
                    ft.DataCell(ft.Text(f"{_n(o.get('fotos'))} de {_n(o.get('cajas_registradas'))}", size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(f"{_fh(o.get('pickeado_en'))} · {o.get('pickeado_por') or '—'}", size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(", ".join(en_carga) or "—", size=12, color=UI["acento"] if en_carga else UI["texto_3"])),
                ]))
        self.tabla_ots.rows = filas
        self.txt_vacio_ots.visible = not filas

    def abrir_ot(self, orden_id):
        if not orden_id:
            return
        self.ot = next((o for o in self.ots if o.get("orden_id") == orden_id), None)
        try:
            self.cajas = list(self._rpc("wms_ot_cajas_detalle", {"p_orden_id": int(orden_id)}) or [])
        except Exception as ex:
            self._notificar(f"No se pudieron leer las cajas: {_error(ex)}", "#B91C1C")
            return
        if self.ot is None:
            self.ot = {"orden_id": orden_id, "numero_ov": "", "pallets": []}
        self.sel_cajas = set()
        self._pintar_ot()
        self.contenedor.content = self.sub_ot
        self.page.update()

    def _recargar_ot(self):
        if not self.ot:
            return
        oid = self.ot.get("orden_id")
        self.cargar_todo(forzar=True)
        if any(o.get("orden_id") == oid for o in self.ots):
            self.abrir_ot(oid)
        else:
            self.sel_sub_cargas(0)

    def _pintar_ot(self):
        o = self.ot or {}
        self.lbl_ot.value = str(o.get("numero_ov") or "")
        self.chip_ot.content = _chip("Quedan pallets en Santiago" if o.get("parcial") else "Lista para carga",
                                     UI["alerta"] if o.get("parcial") else "#A78BFA")
        pallets = o.get("pallets") or []
        self.lbl_ot_meta.value = (f"Pickeada {_fh(o.get('pickeado_en'))} · {o.get('pickeado_por') or '—'}  ·  "
                                  f"{len(pallets)} pallets  ·  {_miles(sum(_n(p.get('unidades')) for p in pallets))} UN  ·  "
                                  f"{_n(o.get('fotos'))} cajas con foto")
        self.btn_reabrir.visible = not o.get("parcial")
        tarjetas = []
        for p in pallets:
            est = p.get("estado_carga")
            color = COLOR_ITEM.get(est, UI["texto_3"])
            tarjetas.append(ft.Container(
                col={"xs": 12, "sm": 6, "md": 4, "lg": 3},
                padding=12, border_radius=8, bgcolor=UI["card_alt"],
                border=ft.Border(left=ft.BorderSide(3, color), top=ft.BorderSide(1, UI["borde"]),
                                 right=ft.BorderSide(1, UI["borde"]), bottom=ft.BorderSide(1, UI["borde"])),
                content=ft.Column([
                    ft.Row([ft.Text(str(p.get("lpn") or ""), size=13.5, weight=ft.FontWeight.W_700, color=UI["texto"], expand=True),
                            _chip(f"{p.get('carga')} · {NOMBRE_ITEM.get(est, est)}" if p.get("carga") else "Sin carga", color)],
                           spacing=6),
                    ft.Text(f"{_n(p.get('cajas'))} cajas · {_miles(p.get('unidades'))} UN · {p.get('skus')} SKU",
                            size=12, color=UI["texto"]),
                    ft.TextButton("Imprimir etiqueta LPN", icon=ft.Icons.PRINT_OUTLINED,
                                  on_click=lambda e, l=p.get("lpn"): self._imprimir_lpn(l)),
                ], spacing=4, tight=True),
            ))
        self.fila_pallets.controls = tarjetas or [ft.Text("Sin pallets por cargar.", size=12, color=UI["texto_2"])]
        self._pintar_cajas()

    def _pintar_cajas(self):
        filas = []
        for c in self.cajas:
            cid = c.get("id")
            filas.append(ft.DataRow(
                selected=cid in self.sel_cajas,
                on_select_change=lambda e, x=cid: self._alternar_caja(x),
                cells=[
                    ft.DataCell(ft.Text(str(c.get("lpn") or ""), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(str(c.get("sku") or ""), size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"])),
                    ft.DataCell(ft.Text(str(c.get("descripcion") or "")[:38], size=12, color=UI["texto_2"],
                                        tooltip=str(c.get("descripcion") or ""))),
                    ft.DataCell(ft.Text(str(c.get("lote") or "S/L"), size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(str(c.get("fecha_vencimiento_cl") or "S/F"), size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(str(c.get("fecha_leida") or "—"), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(_miles(c.get("unidades")), size=12.5, color=UI["texto"])),
                    ft.DataCell(ft.Text(str(c.get("ubicacion") or "—"), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(f"{c.get('usuario') or ''} {_fh(c.get('creado_en'))}", size=11.5, color=UI["texto_3"])),
                    ft.DataCell(ft.TextButton("Ver", on_click=lambda e, ruta=c.get("foto_path"): self._ver_foto(ruta))
                                if c.get("foto_path") else ft.Text("—", size=12, color=UI["texto_3"])),
                ]))
        self.tabla_cajas.rows = filas
        n = len(self.sel_cajas)
        un = sum(_n(c.get("unidades")) for c in self.cajas if c.get("id") in self.sel_cajas)
        self.lbl_sel.value = f"{n} caja(s) elegida(s) · {_miles(un)} UN" if n else "Ninguna caja elegida"

    def _alternar_caja(self, cid):
        if cid in self.sel_cajas:
            self.sel_cajas.discard(cid)
        else:
            self.sel_cajas.add(cid)
        self._pintar_cajas()
        self.page.update()

    def _cajas_elegidas(self) -> list:
        if not self.sel_cajas:
            self._notificar("Marque primero las cajas en la tabla.", "#D97706")
            return []
        return sorted(int(x) for x in self.sel_cajas)

    def _imprimir_lpn(self, lpn):
        """Reimprime la etiqueta LPN de un pallet (por ejemplo, el pallet nuevo al mover cajas)."""
        try:
            numero = int(str(lpn or "").upper().replace("LPN-", "").strip())
        except ValueError:
            self._notificar(f"{lpn} no es un LPN numérico.", "#D97706")
            return
        try:
            from servicios.etiquetas_impresion import generar_pdf_lpn
            os.makedirs("reportes_cargas", exist_ok=True)
            ruta = os.path.join("reportes_cargas", f"Etiqueta_{lpn}_{datetime.now().strftime('%H%M%S')}.pdf")
            generar_pdf_lpn(numero, numero, self._bodega(), ruta)
        except Exception as ex:
            self._notificar(f"No se pudo generar la etiqueta: {_error(ex)}", "#B91C1C")
            return
        descargar_o_abrir_archivo(self.page, ruta)

    # ---------------- Fotos (registro interno de Santiago) ----------------
    def _urls_firmadas(self, rutas: list) -> dict:
        urls = {}
        if not rutas:
            return urls
        try:
            firmadas = supabase.storage.from_("fotos-picking").create_signed_urls(rutas, 3600) or []
            for f in firmadas:
                ruta = f.get("path") or f.get("name")
                url = f.get("signedURL") or f.get("signedUrl") or f.get("signed_url")
                if ruta and url:
                    urls[ruta] = url if url.startswith("http") else f"{SUPABASE_URL}/storage/v1{url}"
        except Exception as ex:
            self._notificar(f"No se pudieron abrir las fotos: {_error(ex)}", "#B45309")
        return urls

    def _ver_foto(self, ruta):
        url = self._urls_firmadas([ruta]).get(ruta)
        if url:
            self._abrir_url(url)

    def _dialogo_fotos(self):
        cajas = self.cajas
        urls = self._urls_firmadas([c["foto_path"] for c in cajas if c.get("foto_path")])
        por_lpn = {}
        for c in cajas:
            por_lpn.setdefault(c.get("lpn") or "-", []).append(c)
        bloques = []
        for lpn, lista in por_lpn.items():
            tarjetas = []
            for c in lista:
                url = urls.get(c.get("foto_path") or "")
                tarjetas.append(ft.Container(
                    width=170, padding=8, border_radius=8, bgcolor=UI["card_alt"], border=ft.Border.all(1, UI["borde"]),
                    content=ft.Column([
                        ft.Image(src=url, width=154, height=116) if url else
                        ft.Container(width=154, height=116, border_radius=6, bgcolor=UI["bg"], alignment=ft.Alignment.CENTER,
                                     content=ft.Text("sin foto", size=11, color=UI["texto_3"])),
                        ft.Text(f"{c.get('sku')} · {c.get('unidades')} UN", size=11.5, weight=ft.FontWeight.W_600, color=UI["texto"]),
                        ft.Text(f"Lote {c.get('lote')} · vence {c.get('fecha_vencimiento_cl') or 'S/F'}", size=10.5, color=UI["texto_2"]),
                        ft.Text(f"Leído: {c.get('fecha_leida') or '-'} · {c.get('usuario') or ''}", size=10.5, color=UI["texto_3"]),
                    ], spacing=3, tight=True),
                    tooltip="Clic para ver la foto en grande" if url else None,
                    on_click=(lambda e, u=url: self._abrir_url(u)) if url else None, ink=bool(url),
                ))
            bloques.append(ft.Column([
                ft.Text(f"{lpn} · {len(lista)} cajas · {_miles(sum(_n(x.get('unidades')) for x in lista))} UN",
                        size=13, weight=ft.FontWeight.W_700, color=UI["texto"]),
                ft.Row(tarjetas, wrap=True, spacing=8, run_spacing=8),
            ], spacing=6))
        if not bloques:
            bloques = [ft.Text("Esta OT no tiene cajas registradas con foto.", size=12, color=UI["texto_2"])]
        self._dialogo(f"Fotos de la fecha · {(self.ot or {}).get('numero_ov') or ''}",
                      ft.Container(height=560, content=ft.Column(bloques, spacing=14, scroll=ft.ScrollMode.AUTO)),
                      [ui_boton("Cerrar", None, self._cerrar_dialogo, "texto")], ancho=760)

    def _abrir_url(self, url):
        import inspect
        if getattr(self.page, "launch_url", None) is None:
            # Flet nuevo (sin page.launch_url): la foto se muestra aquí, con enlace para abrirla aparte
            self._dialogo("Foto de la caja", ft.Column([
                ft.Image(src=url, width=640, height=480),
                ft.TextButton("Abrir en pestaña nueva", icon=ft.Icons.OPEN_IN_NEW_ROUNDED, url=url),
            ], spacing=8, tight=True), [ui_boton("Cerrar", None, self._cerrar_dialogo, "texto")], ancho=660)
            return
        try:
            if inspect.iscoroutinefunction(self.page.launch_url):
                async def _ir():
                    await self.page.launch_url(url)
                self.page.run_task(_ir)
            else:
                self.page.launch_url(url)
        except Exception:
            pass

    # ---------------- Ajustes ----------------
    def _dialogo_lote(self):
        ids = self._cajas_elegidas()
        if not ids:
            return
        elegidas = [c for c in self.cajas if c.get("id") in self.sel_cajas]
        skus = sorted({str(c.get("sku")) for c in elegidas})
        txt_lote = _campo("Lote correcto", 200, value=str(elegidas[0].get("lote") or ""))
        txt_venc = _campo("Vencimiento (DD-MM-AAAA)", 200, value=str(elegidas[0].get("fecha_vencimiento_cl") or ""))
        txt_motivo = _campo("Motivo", 420, multiline=True)
        sw_stock = ft.Switch(label="Corregir también el stock de Santiago (devuelve el lote anterior y descuenta el nuevo)",
                             value=True, active_color=UI["exito"])

        def confirmar(e=None):
            if len((txt_motivo.value or "").strip()) < 4:
                self._notificar("Escriba el motivo.", "#D97706")
                return
            try:
                r = self._rpc("wms_ot_ajustar_lote", {
                    "p_caja_ids": ids, "p_lote": (txt_lote.value or "").strip(), "p_vencimiento": (txt_venc.value or "").strip(),
                    "p_motivo": txt_motivo.value.strip(), "p_usuario": self._usuario(), "p_mover_stock": bool(sw_stock.value),
                }) or {}
            except Exception as ex:
                self._notificar(f"No se pudo cambiar el lote: {_error(ex)}", "#B91C1C")
                return
            self._cerrar_dialogo()
            sin = _n(r.get("stock_sin_registro"))
            self._notificar(f"{r.get('cajas')} caja(s) corregidas en {r.get('numero_ov')}."
                            + (f" Atención: {sin} UN del lote nuevo no estaban en el stock (revisar con conteo)." if sin else ""),
                            "#B45309" if sin else "#047857")
            self._recargar_ot()

        self._dialogo("Cambiar lote / fecha", ft.Column([
            ft.Text(f"{len(ids)} caja(s) · {', '.join(skus)} · {_miles(sum(_n(c.get('unidades')) for c in elegidas))} UN",
                    size=12.5, color=UI["texto"]),
            ft.Row([txt_lote, txt_venc], spacing=10, wrap=True),
            txt_motivo, sw_stock,
            ft.Text("El packing list de la OT se actualiza: Concepción recibirá con el lote corregido.", size=11.5, color=UI["texto_3"]),
        ], spacing=8, tight=True), [
            ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
            ui_boton("Guardar", ft.Icons.SAVE_ROUNDED, confirmar),
        ])

    def _dialogo_mover(self):
        ids = self._cajas_elegidas()
        if not ids:
            return
        lpns = [str(p.get("lpn")) for p in (self.ot or {}).get("pallets") or []]
        dd = ft.Dropdown(
            label="Pallet de destino", dense=True, width=300, value="NUEVO",
            options=[ft.DropdownOption(key="NUEVO", text="Pallet nuevo (LPN nuevo)")] + [ft.DropdownOption(key=l, text=l) for l in lpns],
            bgcolor=UI["input"], border_color=UI["borde"], focused_border_color=UI["acento"],
            text_style=ft.TextStyle(size=12, color=UI["texto"]), border_radius=6,
        )
        txt_motivo = _campo("Motivo", 420, multiline=True)

        def confirmar(e=None):
            if len((txt_motivo.value or "").strip()) < 4:
                self._notificar("Escriba el motivo.", "#D97706")
                return
            try:
                r = self._rpc("wms_ot_mover_cajas", {
                    "p_caja_ids": ids, "p_lpn_destino": None if dd.value == "NUEVO" else dd.value,
                    "p_motivo": txt_motivo.value.strip(), "p_usuario": self._usuario(),
                }) or {}
            except Exception as ex:
                self._notificar(f"No se pudieron mover las cajas: {_error(ex)}", "#B91C1C")
                return
            self._cerrar_dialogo()
            borrados = r.get("pallets_eliminados") or []
            self._notificar(f"{r.get('movidas')} caja(s) movidas a {r.get('lpn_destino')}"
                            + (" (pallet nuevo: imprima su etiqueta con el botón de su tarjeta y péguela)" if r.get("nuevo") else "")
                            + (f". Pallets que quedaron vacíos: {', '.join(borrados)}" if borrados else "."), "#047857")
            self._recargar_ot()

        self._dialogo("Mover cajas a otro pallet", ft.Column([
            ft.Text(f"{len(ids)} caja(s) elegida(s)", size=12.5, color=UI["texto"]),
            dd, txt_motivo,
            ft.Text("El pallet que quede vacío se elimina. Si está en una carga abierta, la carga se actualiza sola.",
                    size=11.5, color=UI["texto_3"]),
        ], spacing=8, tight=True), [
            ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
            ui_boton("Mover", ft.Icons.MOVE_UP_ROUNDED, confirmar),
        ])

    def _dialogo_reabrir(self):
        o = self.ot or {}
        txt_motivo = _campo("Motivo", 420, multiline=True)

        def confirmar(e=None):
            if len((txt_motivo.value or "").strip()) < 4:
                self._notificar("Escriba el motivo.", "#D97706")
                return
            try:
                self._rpc("wms_ot_reabrir_picking", {"p_orden_id": int(o.get("orden_id")), "p_motivo": txt_motivo.value.strip(),
                                                     "p_usuario": self._usuario()})
            except Exception as ex:
                self._notificar(f"No se pudo reabrir: {_error(ex)}", "#B91C1C")
                return
            self._cerrar_dialogo()
            self._notificar(f"{o.get('numero_ov')} volvió a picking. El operador la abre en el celular (Picking OT) y sigue en su último pallet.",
                            "#B45309")
            self.cargar_todo(forzar=True)
            self.sel_sub_cargas(0)

        self._dialogo(f"Reabrir {o.get('numero_ov')} a picking", ft.Column([
            ft.Text("La OT vuelve a la cola de picking con todo lo ya pickeado. Su último pallet se reabre para agregar o quitar cajas. "
                    "Si estaba en una carga abierta, sale de esa carga.", size=12.5, color=UI["texto_2"]),
            txt_motivo,
        ], spacing=8, tight=True), [
            ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
            ui_boton("Reabrir", ft.Icons.UNDO_ROUNDED, confirmar, "peligro"),
        ])

    def _dialogo_historial(self):
        o = self.ot or {}
        try:
            lista = list(self._rpc("wms_ot_ajustes_lista", {"p_orden_id": int(o.get("orden_id"))}) or [])
        except Exception as ex:
            self._notificar(f"No se pudo leer el historial: {_error(ex)}", "#B91C1C")
            return
        nombres = {"CAMBIO_LOTE": "Cambio de lote", "MOVER_CAJAS": "Cajas movidas", "REABRIR_PICKING": "Reabierta a picking"}
        filas = []
        for a in lista:
            det = a.get("detalle") or {}
            if a.get("tipo") == "CAMBIO_LOTE":
                texto = "; ".join(f"{c.get('sku')} {c.get('lpn')}: {c.get('antes')} → {c.get('despues')}" for c in det.get("cajas") or [])
            elif a.get("tipo") == "MOVER_CAJAS":
                texto = f"{len(det.get('cajas') or [])} caja(s) → {det.get('hacia')}"
            else:
                texto = ""
            filas.append(ft.Column([
                ft.Text(f"{_fh(a.get('creado_en'))} · {nombres.get(a.get('tipo'), a.get('tipo'))} · {a.get('usuario') or ''}",
                        size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"]),
                ft.Text(f"Motivo: {a.get('motivo') or '—'}", size=12, color=UI["texto_2"]),
                *([ft.Text(texto[:600], size=11.5, color=UI["texto_3"])] if texto else []),
            ], spacing=2, tight=True))
        self._dialogo(f"Ajustes de {o.get('numero_ov')}",
                      ft.Container(height=380, content=ft.Column(filas or [ft.Text("Sin ajustes.", size=12, color=UI["texto_2"])],
                                                                 spacing=10, scroll=ft.ScrollMode.AUTO)),
                      [ui_boton("Cerrar", None, self._cerrar_dialogo, "texto")], ancho=620)

    # ==================================================================
    # Cargas de camión
    # ==================================================================
    def _pintar_cargas(self):
        filas = []
        for c in self.cargas:
            est = str(c.get("estado") or "")
            total, hechos = _n(c.get("total")), _n(c.get("cargados"))
            filas.append(ft.DataRow(
                on_select_change=lambda e, cid=c.get("id"): self.abrir_carga(cid),
                cells=[
                    ft.DataCell(ft.Text(str(c.get("numero") or ""), size=13, weight=ft.FontWeight.W_700, color=UI["acento"])),
                    ft.DataCell(ft.Text(str(c.get("patente") or ""), size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"])),
                    ft.DataCell(ft.Text(str(c.get("contenedor") or "—"), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(str(c.get("destino") or "—"), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(str(c.get("ordenes") or "—")[:60], size=12, color=UI["texto"], tooltip=str(c.get("ordenes") or ""))),
                    ft.DataCell(ft.Text(f"{hechos} / {total}", size=12.5, weight=ft.FontWeight.W_600,
                                        color=UI["exito"] if total and hechos == total else UI["texto"])),
                    ft.DataCell(_chip(est.capitalize(), COLOR_CARGA.get(est, UI["texto_2"]))),
                    ft.DataCell(ft.Text(f"{_fh(c.get('creado_en'))} · {c.get('creado_por') or ''}", size=11.5, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(f"{_fh(c.get('cerrado_en'))} · {c.get('cerrado_por') or ''}" if c.get("cerrado_en") else "—",
                                        size=11.5, color=UI["texto_2"])),
                ]))
        self.tabla_cargas.rows = filas
        self.txt_vacio_cargas.visible = not filas

    def abrir_carga(self, carga_id):
        if not carga_id:
            return
        try:
            self.carga = self._rpc("wms_carga_detalle", {"p_carga_id": int(carga_id)})
        except Exception as ex:
            self._notificar(f"No se pudo abrir la carga: {_error(ex)}", "#B91C1C")
            return
        self._pintar_carga()
        self.contenedor.content = self.sub_carga
        self.page.update()

    def _accion_carga(self, funcion: str, params: dict, ok: str = None):
        try:
            r = self._rpc(funcion, {**params, "p_usuario": self._usuario()}) or {}
        except Exception as ex:
            self._notificar(f"No se pudo: {_error(ex)}", "#B91C1C")
            return None
        self.carga = r.get("carga") if isinstance(r.get("carga"), dict) else r
        if ok:
            self._notificar(ok, "#047857")
        self._pintar_carga()
        self.page.update()
        return r

    def _pintar_carga(self):
        c = self.carga or {}
        est = str(c.get("estado") or "")
        abierta = est == "ABIERTA"
        total, hechos = _n(c.get("total")), _n(c.get("cargados"))
        self.lbl_carga.value = f"{c.get('numero') or ''} · {c.get('patente') or ''}"
        self.chip_carga.content = _chip(est.capitalize(), COLOR_CARGA.get(est, UI["texto_2"]))
        partes = [p for p in [f"Contenedor {c.get('contenedor')}" if c.get("contenedor") else "",
                              f"Chofer {c.get('chofer')}" if c.get("chofer") else "",
                              str(c.get("destino") or ""),
                              f"{hechos} de {total} cargados",
                              f"{_n(c.get('quitados'))} para otro camión" if _n(c.get("quitados")) else "",
                              f"Creada {_fh(c.get('creado_en'))} · {c.get('creado_por') or ''}",
                              f"Cerrada {_fh(c.get('cerrado_en'))} · {c.get('cerrado_por') or ''}" if c.get("cerrado_en") else "",
                              str(c.get("observacion") or "")] if p]
        self.lbl_carga_meta.value = "  ·  ".join(partes)
        self.barra_carga.value = (hechos / total) if total else 0
        self.txt_agregar.value = ""
        self.txt_scan.value = ""
        self.fila_acciones_carga.controls = ([
            self.txt_agregar,
            ui_boton("Agregar", ft.Icons.ADD_ROUNDED, lambda e: self._agregar_orden(), "secundario"),
            self.txt_scan,
            ui_boton("Marcar cargado", ft.Icons.UPLOAD_ROUNDED, lambda e: self._marcar_cargado(), "secundario"),
            ui_boton("Cerrar carga", ft.Icons.LOCK_OUTLINE_ROUNDED, lambda e: self._dialogo_cerrar_carga()),
            ui_boton("Anular", ft.Icons.BLOCK_ROUNDED, lambda e: self._dialogo_anular(), "peligro"),
        ] if abierta else []) + [ui_boton("Exportar", ft.Icons.DOWNLOAD_ROUNDED, lambda e: self._exportar_carga(), "secundario")]

        filas = []
        for o in c.get("ordenes") or []:
            for i in o.get("items") or []:
                ie = str(i.get("estado") or "")
                color = COLOR_ITEM.get(ie, UI["texto_2"])
                acciones = []
                if abierta and ie != "CARGADO":
                    acciones.append(ft.IconButton(icon=ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED, icon_color=UI["exito"], icon_size=18,
                                                  tooltip="Marcar cargado",
                                                  on_click=lambda e, cod=i.get("codigo"): self._marcar_cargado(cod)))
                if abierta and ie == "CARGADO":
                    acciones.append(ft.IconButton(icon=ft.Icons.UNDO_ROUNDED, icon_color=UI["alerta"], icon_size=18,
                                                  tooltip="Se bajó del camión (desmarcar)",
                                                  on_click=lambda e, cod=i.get("codigo"): self._cambiar_item(cod, "DESMARCAR")))
                if abierta and ie != "QUITADO":
                    acciones.append(ft.IconButton(icon=ft.Icons.SCHEDULE_ROUNDED, icon_color=UI["texto_2"], icon_size=18,
                                                  tooltip="Dejar para otro camión",
                                                  on_click=lambda e, cod=i.get("codigo"): self._dialogo_quitar_item(cod)))
                filas.append(ft.DataRow(cells=[
                    ft.DataCell(ft.Text(f"{o.get('numero_ov')} ({o.get('tipo')})", size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"])),
                    ft.DataCell(ft.Text(f"{'Pallet' if i.get('tipo') == 'PALLET' else 'Bulto'} {i.get('n')}/{i.get('total')}",
                                        size=12.5, color=UI["texto"])),
                    ft.DataCell(ft.Text(str(i.get("codigo") or ""), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(_miles(i.get("cajas")) if i.get("cajas") else "—", size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(_miles(i.get("unidades")) if i.get("unidades") else "—", size=12, color=UI["texto_2"])),
                    ft.DataCell(_chip(NOMBRE_ITEM.get(ie, ie), color)),
                    ft.DataCell(ft.Text(f"{i.get('cargado_por') or ''} {_fh(i.get('cargado_en')) if i.get('cargado_en') else ''}".strip() or "—",
                                        size=11.5, color=UI["texto_3"])),
                    ft.DataCell(ft.Text(str(i.get("motivo") or ""), size=11.5, color=UI["texto_2"], max_lines=2,
                                        overflow=ft.TextOverflow.ELLIPSIS)),
                    ft.DataCell(ft.Row(acciones, spacing=0, tight=True)),
                ]))
        self.tabla_items.rows = filas

    def _agregar_orden(self):
        num = (self.txt_agregar.value or "").strip()
        if not num or not self.carga:
            self._notificar("Escriba el número de la OT u OV.", "#D97706")
            return
        self._accion_carga("wms_carga_agregar_orden", {"p_carga_id": int(self.carga.get("id")), "p_numero": num},
                           f"{num} agregada a la carga.")

    def _marcar_cargado(self, codigo: str = None):
        cod = (codigo or self.txt_scan.value or "").strip()
        if not cod or not self.carga:
            return
        r = self._accion_carga("wms_carga_escanear", {"p_carga_id": int(self.carga.get("id")), "p_codigo": cod})
        if r:
            self._notificar(f"{'Pallet' if r.get('tipo') == 'PALLET' else 'Bulto'} {r.get('n')}/{r.get('total')} de "
                            f"{r.get('numero_ov')} {'ya estaba cargado' if r.get('ya_cargado') else 'cargado'}.",
                            "#B45309" if r.get("ya_cargado") else "#047857")

    def _cambiar_item(self, codigo: str, accion: str, motivo: str = None):
        self._accion_carga("wms_carga_cambiar_item", {"p_carga_id": int(self.carga.get("id")), "p_codigo": codigo,
                                                      "p_accion": accion, "p_motivo": motivo})

    def _dialogo_quitar_item(self, codigo: str):
        txt = _campo("Motivo", 420)

        def confirmar(e=None):
            if len((txt.value or "").strip()) < 3:
                self._notificar("Escriba el motivo.", "#D97706")
                return
            self._cerrar_dialogo()
            self._cambiar_item(codigo, "QUITAR", txt.value.strip())

        self._dialogo(f"Dejar {codigo} para otro camión", ft.Column([
            ft.Text("Queda en bodega y se puede agregar a la próxima carga.", size=12.5, color=UI["texto_2"]), txt,
        ], spacing=8, tight=True), [ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
                                    ui_boton("Aceptar", ft.Icons.SCHEDULE_ROUNDED, confirmar)])

    def _dialogo_cerrar_carga(self):
        c = self.carga or {}
        pend = _n(c.get("pendientes"))
        txt = _campo("Motivo (los que faltan quedan para otro camión)", 420) if pend else None

        def confirmar(e=None):
            motivo = (txt.value or "").strip() if txt else None
            if pend and len(motivo or "") < 3:
                self._notificar("Escriba el motivo de lo que no se subió.", "#D97706")
                return
            self._cerrar_dialogo()
            r = self._accion_carga("wms_carga_cerrar", {"p_carga_id": int(c.get("id")), "p_motivo_pendientes": motivo})
            if r:
                ots = r.get("ot_en_transito") or []
                self._notificar(f"Carga {r.get('numero')} cerrada."
                                + (" En tránsito a Concepción: " + ", ".join(f"{o.get('numero_ov')} ({o.get('pallets')} pallets)" for o in ots)
                                   if ots else ""), "#047857")
                self.cargar_todo(forzar=True)

        self._dialogo(f"Cerrar carga {c.get('numero')}", ft.Column([
            ft.Text(f"Patente {c.get('patente')} · {_n(c.get('cargados'))} de {_n(c.get('total'))} cargados.", size=12.5, color=UI["texto"]),
            ft.Text("Las OT pasan a EN TRÁNSITO a Concepción. Las OV quedan registradas (siguen su facturación y ruteo).",
                    size=12, color=UI["texto_2"]),
            *([ft.Text(f"Faltan {pend} por subir.", size=12.5, weight=ft.FontWeight.W_600, color=UI["alerta"]), txt] if pend else []),
        ], spacing=8, tight=True), [ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
                                    ui_boton("Cerrar carga", ft.Icons.LOCK_OUTLINE_ROUNDED, confirmar)])

    def _dialogo_anular(self):
        c = self.carga or {}
        txt = _campo("Motivo", 420)

        def confirmar(e=None):
            if len((txt.value or "").strip()) < 4:
                self._notificar("Escriba el motivo.", "#D97706")
                return
            self._cerrar_dialogo()
            if self._accion_carga("wms_carga_anular", {"p_carga_id": int(c.get("id")), "p_motivo": txt.value.strip()},
                                  f"Carga {c.get('numero')} anulada."):
                self.cargar_todo(forzar=True)

        self._dialogo(f"Anular carga {c.get('numero')}", ft.Column([
            ft.Text("Las OT y OV de esta carga quedan libres para otra carga. No cambia su estado.", size=12.5, color=UI["texto_2"]),
            txt,
        ], spacing=8, tight=True), [ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
                                    ui_boton("Anular", ft.Icons.BLOCK_ROUNDED, confirmar, "peligro")])

    def _dialogo_nueva_carga(self):
        txt_patente = _campo("Patente del camión *", 220)
        txt_contenedor = _campo("N° de contenedor (opcional)", 220)
        txt_chofer = _campo("Chofer (opcional)", 220)
        es_ccp = "CONCEPCION" in self._bodega().upper().replace("Ó", "O")
        dd_destino = ft.Dropdown(
            label="Destino", dense=True, width=220, value="Clientes (ruta)" if es_ccp else "Bodega Concepción",
            options=[ft.DropdownOption(key=d, text=d) for d in ["Bodega Concepción", "Clientes (ruta)", "Otro"]],
            bgcolor=UI["input"], border_color=UI["borde"], focused_border_color=UI["acento"],
            text_style=ft.TextStyle(size=12, color=UI["texto"]), border_radius=6,
        )

        def confirmar(e=None):
            try:
                r = self._rpc("wms_carga_crear", {
                    "p_bodega": self._bodega(), "p_patente": (txt_patente.value or "").strip(),
                    "p_contenedor": (txt_contenedor.value or "").strip(), "p_chofer": (txt_chofer.value or "").strip(),
                    "p_destino": dd_destino.value, "p_usuario": self._usuario(),
                }) or {}
            except Exception as ex:
                self._notificar(f"No se pudo crear la carga: {_error(ex)}", "#B91C1C")
                return
            self._cerrar_dialogo()
            self._notificar(f"Carga {r.get('numero')} creada. Agregue las OT u OV.", "#047857")
            self.cargar_todo(forzar=True)
            self.abrir_carga(r.get("id"))

        self._dialogo("Nueva carga de camión", ft.Column([
            ft.Row([txt_patente, txt_contenedor], spacing=10, wrap=True),
            ft.Row([txt_chofer, dd_destino], spacing=10, wrap=True),
        ], spacing=8, tight=True), [ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
                                    ui_boton("Crear", ft.Icons.ADD_ROUNDED, confirmar)])

    def _exportar_carga(self):
        c = self.carga or {}
        filas = []
        for o in c.get("ordenes") or []:
            for i in o.get("items") or []:
                filas.append({
                    "Carga": c.get("numero"), "Patente": c.get("patente"), "Contenedor": c.get("contenedor"),
                    "Chofer": c.get("chofer"), "Destino": c.get("destino"), "Orden": o.get("numero_ov"), "Tipo": o.get("tipo"),
                    "Cliente": o.get("cliente"), "Pallet / bulto": f"{i.get('n')}/{i.get('total')}", "Código": i.get("codigo"),
                    "Cajas": i.get("cajas"), "Unidades": i.get("unidades"), "Estado": NOMBRE_ITEM.get(i.get("estado"), i.get("estado")),
                    "Cargado por": i.get("cargado_por"), "Fecha": _fh(i.get("cargado_en")) if i.get("cargado_en") else "",
                    "Motivo": i.get("motivo"),
                })
        if not filas:
            self._notificar("La carga no tiene pallets ni bultos.", "#D97706")
            return
        os.makedirs("reportes_cargas", exist_ok=True)
        ruta = os.path.join("reportes_cargas", f"Carga_{c.get('numero')}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
        pd.DataFrame(filas).to_excel(ruta, index=False)
        descargar_o_abrir_archivo(self.page, ruta)

    # ==================================================================
    # Navegación (submenú del portal)
    # ==================================================================
    def sel_sub_cargas(self, idx: int):
        self.vista_actual = 1 if idx == 1 else 0
        self.cargar_todo()
        self.contenedor.content = self.sub_cargas if self.vista_actual == 1 else self.sub_ots
        try:
            self.page.update()
        except Exception:
            pass

    def refrescar(self, e=None):
        if self.contenedor.content is self.sub_ot and self.ot:
            self._recargar_ot()
        elif self.contenedor.content is self.sub_carga and self.carga:
            self.cargar_todo(forzar=True)
            self.abrir_carga(self.carga.get("id"))
        else:
            self.sel_sub_cargas(self.vista_actual)
