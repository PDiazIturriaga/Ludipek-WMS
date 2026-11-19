import os
from datetime import datetime
import pandas as pd
import flet as ft
from dependencias import *


# Colores por resultado (pallet y línea)
COLOR_RESULTADO = {
    "PENDIENTE": "#94A3B8",
    "RECIBIDO_CCP": "#10B981",
    "CONFORME": "#10B981",
    "RECIBIDO_CON_DIFERENCIAS": "#F59E0B",
    "FALTANTE": "#F59E0B",
    "SOBRANTE": "#38BDF8",
    "LOTE_DISTINTO": "#A78BFA",
    "NO_LLEGO": "#DC2626",
}
NOMBRE_RESULTADO = {
    "PENDIENTE": "Por recibir",
    "RECIBIDO_CCP": "Conforme",
    "CONFORME": "Conforme",
    "RECIBIDO_CON_DIFERENCIAS": "Con diferencias",
    "FALTANTE": "Faltante",
    "SOBRANTE": "Sobrante",
    "LOTE_DISTINTO": "Lote / venc. distinto",
    "NO_LLEGO": "No llegó",
}
NOMBRE_ESTADO_OT = {
    "EN_TRANSITO_CCP": ("En camino", "#38BDF8"),
    "RECEPCION_CCP_EN_PROCESO": ("Recibiendo", "#0284C7"),
    "RECIBIDO_CCP": ("Recibida conforme", "#10B981"),
    "RECIBIDO_CCP_CON_DIFERENCIAS": ("Recibida con diferencias", "#F59E0B"),
}


def _fh(valor) -> str:
    return formatear_fecha_hora_chile(valor) if valor else "—"


def _n(valor) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _error(ex) -> str:
    """Mensaje legible de un error de Supabase (las funciones wms_* responden "WMS: ...")."""
    msg = getattr(ex, "message", None) or str(ex)
    if isinstance(msg, dict):
        msg = msg.get("message") or str(msg)
    return str(msg).replace("WMS: ", "", 1)


def _chip(texto: str, color: str):
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.16, color),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.5, color)),
        content=ft.Text(texto, size=11, weight=ft.FontWeight.W_600, color=color),
    )


class RecepcionTrasladosCcpModulo:
    """Recepción de traslados Santiago -> Concepción.
    El celular de Concepción recibe pallet por pallet (wms_recibir_pallet_traslado);
    el PC revisa lo despachado contra lo recibido y puede cerrar una OT con pallets que no llegaron."""

    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables
        self.vista_actual = 0          # 0 = en camino / recibiendo · 1 = recibidas
        self.traslados = []            # filas de wms_traslados_ccp(false)
        self.detalle = None            # wms_traslado_ccp_detalle de la OT abierta

        # ---------------- Indicadores ----------------
        self.k_camino = ft.Text("0")
        self.k_recibiendo = ft.Text("0")
        self.k_pallets = ft.Text("0")
        self.k_dif = ft.Text("0")
        self.k_camino_det = ft.Text("", size=11, color=UI["texto_3"])
        self.k_pallets_det = ft.Text("", size=11, color=UI["texto_3"])
        self.k_dif_det = ft.Text("últimos 90 días", size=11, color=UI["texto_3"])

        # ---------------- Bandeja ----------------
        self.txt_buscar = ft.TextField(
            hint_text="Buscar OT", dense=True, width=220, bgcolor=UI["input"], color=UI["texto"],
            border_color=UI["borde"], focused_border_color=UI["acento"], border_radius=6,
            prefix_icon=ft.Icons.SEARCH_ROUNDED, text_style=ft.TextStyle(size=12),
            on_change=lambda e: self._pintar_bandeja(),
        )
        self.tabla_ots = ft.DataTable(
            show_checkbox_column=False,
            heading_row_height=38, data_row_min_height=44, data_row_max_height=52,
            columns=[ft.DataColumn(ft.Text(t, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"]), numeric=num)
                     for t, num in [("OT", False), ("Estado", False), ("Salió de Santiago", False), ("Pallets", True),
                                    ("Unidades recibidas", True), ("Diferencia", True), ("Recibido por", False),
                                    ("Última recepción", False)]],
            rows=[],
        )
        self.txt_vacio = ft.Container(
            visible=False, padding=30, alignment=ft.Alignment.CENTER,
            content=ft.Column([
                ft.Icon(ft.Icons.LOCAL_SHIPPING_OUTLINED, size=40, color=UI["texto_3"]),
                ft.Text("No hay traslados en este grupo.", size=13, color=UI["texto_2"]),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8, tight=True),
        )
        self.pestanas = ui_pestanas(
            [("En camino y recibiendo", ft.Icons.LOCAL_SHIPPING_OUTLINED), ("Recibidas (90 días)", ft.Icons.INVENTORY_ROUNDED)],
            lambda i: self.sel_sub_recepcion_ccp(i),
        )

        self.sub_bandeja = ft.Column([
            ft.ResponsiveRow([
                ui_kpi(self.k_camino, "En camino", ft.Icons.LOCAL_SHIPPING_OUTLINED, UI["acento"], self.k_camino_det),
                ui_kpi(self.k_recibiendo, "Recibiendo ahora", ft.Icons.MOVE_TO_INBOX_ROUNDED, UI["primario"]),
                ui_kpi(self.k_pallets, "Pallets por recibir", ft.Icons.INVENTORY_2_OUTLINED, UI["alerta"], self.k_pallets_det),
                ui_kpi(self.k_dif, "OT con diferencias", ft.Icons.REPORT_PROBLEM_OUTLINED, UI["peligro"], self.k_dif_det),
            ], spacing=12, run_spacing=12),
            ui_tarjeta(
                ft.Column([ui_tabla(self.tabla_ots, 440), self.txt_vacio], spacing=0, tight=True),
                titulo="Traslados Santiago → Concepción",
                subtitulo="Haga clic en una OT para ver pallet por pallet lo despachado y lo recibido",
                icono=ft.Icons.SWAP_HORIZ_ROUNDED,
                acciones=[self.pestanas, self.txt_buscar],
            ),
        ], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)

        # ---------------- Detalle de una OT ----------------
        self.lbl_ot = ft.Text("", size=20, weight=ft.FontWeight.W_700, color=UI["texto"])
        self.chip_estado = ft.Container()
        self.lbl_meta = ft.Text("", size=12, color=UI["texto_2"])
        self.aviso_packing = ft.Container(visible=False)
        self.fila_pallets = ft.ResponsiveRow(spacing=10, run_spacing=10)
        self.sw_solo_dif = ft.Switch(label="Solo diferencias", value=False, active_color=UI["alerta"],
                                     on_change=lambda e: self._pintar_lineas())
        self.tabla_lineas = ft.DataTable(
            heading_row_height=38, data_row_min_height=40, data_row_max_height=48,
            columns=[ft.DataColumn(ft.Text(t, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"]), numeric=num)
                     for t, num in [("Pallet", False), ("SKU", False), ("Descripción", False), ("Lote / venc. enviado", False),
                                    ("Enviado", True), ("Recibido", True), ("Lote / venc. recibido", False),
                                    ("Resultado", False), ("Motivo", False)]],
            rows=[],
        )
        self.btn_cerrar_ot = ui_boton("Cerrar con pallets que no llegaron", ft.Icons.REPORT_PROBLEM_OUTLINED,
                                      lambda e: self._dialogo_cerrar_ot(), "peligro")

        self.sub_detalle = ft.Column([
            ft.Container(
                padding=16, border_radius=10, bgcolor=UI["card"], border=ft.Border.all(1, UI["borde"]),
                content=ft.Row([
                    ft.IconButton(icon=ft.Icons.ARROW_BACK_ROUNDED, icon_color=UI["acento"], tooltip="Volver a la bandeja",
                                  on_click=lambda e: self.sel_sub_recepcion_ccp(self.vista_actual)),
                    ft.Column([ft.Row([self.lbl_ot, self.chip_estado], spacing=12, wrap=True), self.lbl_meta],
                              spacing=4, tight=True, expand=True),
                    ft.Row([
                        self.btn_cerrar_ot,
                        ui_boton("Exportar", ft.Icons.DOWNLOAD_ROUNDED, lambda e: self._exportar_detalle(), "secundario"),
                        ui_boton("Actualizar", ft.Icons.REFRESH_ROUNDED, lambda e: self._recargar_detalle(), "secundario"),
                    ], spacing=8, wrap=True),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
            ),
            self.aviso_packing,
            ui_tarjeta(self.fila_pallets, titulo="Pallets", icono=ft.Icons.INVENTORY_2_OUTLINED,
                       subtitulo="Cada pallet se recibe en el celular de Concepción escaneando su LPN"),
            ui_tarjeta(ui_tabla(self.tabla_lineas, 420), titulo="Productos: enviado vs recibido",
                       icono=ft.Icons.FACT_CHECK_OUTLINED, acciones=[self.sw_solo_dif]),
        ], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)

        self.contenedor = ft.Container(content=self.sub_bandeja, expand=True)
        self.vista = ft.Container(
            padding=16, bgcolor=UI["bg"], expand=True,
            content=ft.Column([
                ui_encabezado(
                    "Recepción de traslados",
                    "Santiago → Concepción · el celular recibe, aquí se revisa",
                    ft.Icons.MOVE_TO_INBOX_ROUNDED,
                    [ui_boton("Actualizar", ft.Icons.REFRESH_ROUNDED, lambda e: self.refrescar(), "secundario"),
                     ui_boton("Exportar diferencias", ft.Icons.DOWNLOAD_ROUNDED, lambda e: self._exportar_diferencias(), "secundario")],
                ),
                self.contenedor,
            ], spacing=14, expand=True),
        )

    # ==================================================================
    # Datos
    # ==================================================================
    def _notificar(self, texto: str, color: str = "#1E3A8A"):
        notificar_global(self.page, texto, color)

    def _validar_bodega(self) -> bool:
        actual = obtener_bodega_activa(self.page).upper().replace("Ó", "O")
        if "CONCEPCION" not in actual:
            self._notificar("Este módulo es de Bodega Concepción. Cambie la bodega activa.", "#B91C1C")
            return False
        return True

    def _rpc(self, nombre: str, params: dict):
        return supabase.rpc(nombre, params).execute().data

    def cargar_bandeja(self, e=None):
        if not self._validar_bodega():
            return
        try:
            self.traslados = list(self._rpc("wms_traslados_ccp", {"p_solo_abiertos": False}) or [])
        except Exception as ex:
            self.traslados = []
            self._notificar(f"No se pudieron leer los traslados: {_error(ex)}", "#B91C1C")
        abiertas = [t for t in self.traslados if t.get("estado") in ("EN_TRANSITO_CCP", "RECEPCION_CCP_EN_PROCESO")]
        en_camino = [t for t in abiertas if t.get("estado") == "EN_TRANSITO_CCP"]
        self.k_camino.value = str(len(en_camino))
        self.k_camino_det.value = f"{sum(_n(t.get('pallets')) for t in en_camino)} pallets"
        self.k_recibiendo.value = str(len(abiertas) - len(en_camino))
        por_recibir = sum(max(0, _n(t.get("pallets")) - _n(t.get("pallets_recibidos")) - _n(t.get("pallets_no_llegaron")))
                          for t in abiertas)
        self.k_pallets.value = str(por_recibir)
        self.k_pallets_det.value = f"{sum(_n(t.get('unidades_despachadas')) for t in abiertas):,} UN en camino".replace(",", ".")
        self.k_dif.value = str(sum(1 for t in self.traslados if _n(t.get("pallets_con_diferencia")) > 0))
        self._pintar_bandeja()

    def _pintar_bandeja(self):
        q = (self.txt_buscar.value or "").strip().upper()
        abiertos = self.vista_actual == 0
        filas = []
        for t in self.traslados:
            es_abierta = t.get("estado") in ("EN_TRANSITO_CCP", "RECEPCION_CCP_EN_PROCESO")
            if es_abierta != abiertos:
                continue
            if q and q not in str(t.get("numero_ot") or "").upper():
                continue
            nombre, color = NOMBRE_ESTADO_OT.get(t.get("estado"), (str(t.get("estado") or "-"), UI["texto_2"]))
            total = _n(t.get("pallets"))
            hechos = _n(t.get("pallets_recibidos")) + _n(t.get("pallets_no_llegaron"))
            dif = _n(t.get("unidades_diferencia"))
            falt_pk = _n(t.get("faltante_packing"))
            filas.append(ft.DataRow(
                on_select_change=lambda e, oid=t.get("orden_id"): self.abrir_detalle(oid),
                cells=[
                    ft.DataCell(ft.Column([
                        ft.Text(str(t.get("numero_ot") or ""), size=13, weight=ft.FontWeight.W_700, color=UI["acento"]),
                        *([ft.Text(f"Enviada con faltante de {falt_pk} UN", size=10.5, color=UI["alerta"])] if falt_pk else []),
                    ], spacing=0, tight=True)),
                    ft.DataCell(_chip(nombre, color)),
                    ft.DataCell(ft.Text(f"{_fh(t.get('despachado_en'))} · {t.get('despachado_por') or '—'}", size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(f"{hechos} / {total}", size=12.5, weight=ft.FontWeight.W_600,
                                        color=UI["exito"] if total and hechos == total else UI["texto"])),
                    ft.DataCell(ft.Text(f"{_n(t.get('unidades_recibidas')):,} / {_n(t.get('unidades_despachadas')):,}".replace(",", "."),
                                        size=12, color=UI["texto"])),
                    ft.DataCell(ft.Text(f"{dif:,} UN".replace(",", ".") if dif else "—", size=12.5, weight=ft.FontWeight.W_600,
                                        color=UI["alerta"] if dif else UI["texto_3"])),
                    ft.DataCell(ft.Text(str(t.get("recibido_por") or "—"), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(_fh(t.get("ultima_recepcion")), size=12, color=UI["texto_2"])),
                ],
            ))
        self.tabla_ots.rows = filas
        self.txt_vacio.visible = not filas
        self.page.update()

    # ==================================================================
    # Detalle
    # ==================================================================
    def abrir_detalle(self, orden_id):
        if not orden_id:
            return
        try:
            self.detalle = self._rpc("wms_traslado_ccp_detalle", {"p_orden_id": int(orden_id)})
        except Exception as ex:
            self._notificar(f"No se pudo abrir la OT: {_error(ex)}", "#B91C1C")
            return
        self._pintar_detalle()
        self.contenedor.content = self.sub_detalle
        self.page.update()

    def _recargar_detalle(self):
        if self.detalle:
            self.abrir_detalle(self.detalle.get("orden_id"))

    def _pallets(self) -> list:
        return list((self.detalle or {}).get("pallets") or [])

    def _pintar_detalle(self):
        d = self.detalle or {}
        estado = str(d.get("estado") or "")
        nombre, color = NOMBRE_ESTADO_OT.get(estado, (estado, UI["texto_2"]))
        self.lbl_ot.value = str(d.get("numero_ot") or "")
        self.chip_estado.content = _chip(nombre, color)
        desp = d.get("despacho") or {}
        pallets = self._pallets()
        total_env = sum(_n(p.get("unidades_despachadas")) for p in pallets)
        total_rec = sum(_n(p.get("unidades_recibidas")) for p in pallets)
        self.lbl_meta.value = (f"Salió de Santiago {_fh(desp.get('cerrado_en'))} · {desp.get('cerrado_por') or '—'}  ·  "
                               f"{len(pallets)} pallets  ·  recibido {total_rec:,} de {total_env:,} UN").replace(",", ".")
        falt = _n(desp.get("faltante_un"))
        self.aviso_packing.visible = falt > 0
        if falt:
            self.aviso_packing.content = ft.Container(
                padding=12, border_radius=8, bgcolor=ft.Colors.with_opacity(0.12, UI["alerta"]),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.5, UI["alerta"])),
                content=ft.Row([
                    ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, color=UI["alerta"]),
                    ft.Text(f"Santiago cerró el packing con faltante de {falt:,} UN ({desp.get('motivo_faltante') or 'sin motivo'}). "
                            "Esas unidades nunca se cargaron: no se esperan en Concepción.".replace(",", "."),
                            size=12, color=UI["texto"], expand=True),
                ], spacing=10),
            )
        self.btn_cerrar_ot.visible = estado in ("EN_TRANSITO_CCP", "RECEPCION_CCP_EN_PROCESO") and any(
            p.get("pendiente") for p in pallets)

        tarjetas = []
        for p in pallets:
            est = str(p.get("estado") or "PENDIENTE")
            col = COLOR_RESULTADO.get(est, UI["texto_2"])
            destino = p.get("lpn_destino")
            lineas_txt = [
                ft.Text(f"{_n(p.get('unidades_recibidas')):,} de {_n(p.get('unidades_despachadas')):,} UN · {p.get('skus')} SKU".replace(",", "."),
                        size=12, color=UI["texto"]),
            ]
            if destino and destino != p.get("lpn"):
                lineas_txt.append(ft.Text(f"Etiqueta nueva en CCP: {destino}", size=11, color=UI["acento"]))
            if p.get("usuario"):
                lineas_txt.append(ft.Text(f"{p.get('usuario')} · {_fh(p.get('fecha'))}", size=11, color=UI["texto_3"]))
            if p.get("observacion"):
                lineas_txt.append(ft.Text(str(p.get("observacion")), size=11, color=UI["alerta"], max_lines=2,
                                          overflow=ft.TextOverflow.ELLIPSIS))
            tarjetas.append(ft.Container(
                col={"xs": 12, "sm": 6, "md": 4, "lg": 3},
                padding=12, border_radius=8, bgcolor=UI["card_alt"],
                border=ft.Border(left=ft.BorderSide(3, col), top=ft.BorderSide(1, UI["borde"]),
                                 right=ft.BorderSide(1, UI["borde"]), bottom=ft.BorderSide(1, UI["borde"])),
                content=ft.Column([
                    ft.Row([ft.Text(str(p.get("lpn") or ""), size=13.5, weight=ft.FontWeight.W_700, color=UI["texto"], expand=True),
                            _chip(NOMBRE_RESULTADO.get(est, est), col)], spacing=6),
                    *lineas_txt,
                ], spacing=4, tight=True),
            ))
        self.fila_pallets.controls = tarjetas or [ft.Text("Esta OT no tiene pallets con LPN en su packing list.", size=12, color=UI["texto_2"])]
        self._pintar_lineas()

    def _pintar_lineas(self):
        solo_dif = bool(self.sw_solo_dif.value)
        filas = []
        for p in self._pallets():
            for l in p.get("lineas") or []:
                res = str(l.get("resultado") or "PENDIENTE")
                if p.get("estado") == "NO_LLEGO":
                    res = "NO_LLEGO"
                if solo_dif and res in ("CONFORME", "PENDIENTE"):
                    continue
                col = COLOR_RESULTADO.get(res, UI["texto_2"])
                env = _n(l.get("unidades"))
                rec = l.get("unidades_recibidas")
                rec_txt = "—" if rec is None and res != "NO_LLEGO" else f"{_n(rec):,}".replace(",", ".")
                lote_env = f"{l.get('lote') or 'S/L'} · {l.get('vencimiento') or 'S/F'}"
                lote_rec = ("—" if l.get("lote_recibido") is None
                            else f"{l.get('lote_recibido')} · {l.get('vencimiento_recibido') or 'S/F'}")
                filas.append(ft.DataRow(cells=[
                    ft.DataCell(ft.Text(str(p.get("lpn") or ""), size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(str(l.get("sku") or ""), size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"])),
                    ft.DataCell(ft.Text(str(l.get("descripcion") or "")[:44], size=12, color=UI["texto_2"],
                                        tooltip=str(l.get("descripcion") or ""))),
                    ft.DataCell(ft.Text(lote_env, size=12, color=UI["texto_2"])),
                    ft.DataCell(ft.Text(f"{env:,}".replace(",", "."), size=12.5, color=UI["texto"])),
                    ft.DataCell(ft.Text(rec_txt, size=12.5, weight=ft.FontWeight.W_600,
                                        color=col if res not in ("CONFORME", "PENDIENTE") else UI["texto"])),
                    ft.DataCell(ft.Text(lote_rec, size=12,
                                        color=COLOR_RESULTADO["LOTE_DISTINTO"] if res == "LOTE_DISTINTO" else UI["texto_2"])),
                    ft.DataCell(_chip(NOMBRE_RESULTADO.get(res, res), col)),
                    ft.DataCell(ft.Text(str(l.get("observacion") or (p.get("observacion") if res == "NO_LLEGO" else "") or ""),
                                        size=11.5, color=UI["texto_2"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)),
                ]))
        self.tabla_lineas.rows = filas
        self.page.update()

    # ==================================================================
    # Cerrar OT con pallets que no llegaron (supervisor)
    # ==================================================================
    def _dialogo_cerrar_ot(self):
        d = self.detalle or {}
        pendientes = [p for p in self._pallets() if p.get("pendiente")]
        if not pendientes:
            self._notificar("No quedan pallets por recibir.", "#D97706")
            return
        motivos = ["El pallet no venía en el camión", "Llega en otro camión", "Pallet extraviado", "Otro"]
        dd_motivo = ft.Dropdown(
            label="Motivo", dense=True, options=[ft.DropdownOption(key=m, text=m) for m in motivos],
            bgcolor=UI["input"], border_color=UI["borde"], focused_border_color=UI["acento"],
            text_style=ft.TextStyle(size=12, color=UI["texto"]), border_radius=6, width=420,
        )
        txt_detalle = ft.TextField(label="Detalle (obligatorio si elige Otro)", dense=True, width=420, multiline=True,
                                   bgcolor=UI["input"], border_color=UI["borde"], color=UI["texto"],
                                   text_style=ft.TextStyle(size=12))

        def cerrar_dialogo(ev=None):
            try:
                self.page.pop_dialog()
            except Exception:
                dlg.open = False
            self.page.update()

        def confirmar(ev=None):
            motivo = dd_motivo.value
            extra = (txt_detalle.value or "").strip()
            if not motivo or (motivo == "Otro" and not extra):
                self._notificar("Indique el motivo.", "#D97706")
                return
            texto = extra if motivo == "Otro" else (f"{motivo} · {extra}" if extra else motivo)
            try:
                r = self._rpc("wms_cerrar_recepcion_traslado", {
                    "p_orden_id": int(d.get("orden_id")),
                    "p_usuario": str(getattr(self.page, "usuario_actual", None) or "PC"),
                    "p_motivo": texto,
                }) or {}
            except Exception as ex:
                self._notificar(f"No se pudo cerrar: {_error(ex)}", "#B91C1C")
                return
            cerrar_dialogo()
            self._notificar(f"{d.get('numero_ot')} cerrada: {r.get('pallets_recibidos', 0)} recibido(s), "
                            f"{r.get('pallets_no_llegaron', 0)} no llegaron.", "#B45309")
            self.cargar_bandeja()
            self._recargar_detalle()

        dlg = ft.AlertDialog(
            bgcolor=UI["card"],
            title=ft.Text(f"Cerrar {d.get('numero_ot')}", size=18, weight=ft.FontWeight.W_700, color=UI["texto"]),
            content=ft.Container(width=440, content=ft.Column([
                ft.Text("Estos pallets quedarán como NO LLEGÓ y la OT se cerrará con diferencias:", size=12.5, color=UI["texto_2"]),
                *[ft.Text(f"•  {p.get('lpn')}  ·  {p.get('skus')} SKU  ·  {_n(p.get('unidades_despachadas')):,} UN".replace(",", "."),
                          size=12.5, color=UI["texto"]) for p in pendientes],
                ft.Container(height=6),
                dd_motivo,
                txt_detalle,
            ], spacing=6, tight=True, scroll=ft.ScrollMode.AUTO)),
            actions=[
                ui_boton("Cancelar", None, cerrar_dialogo, "texto"),
                ui_boton("Cerrar OT", ft.Icons.REPORT_PROBLEM_OUTLINED, confirmar, "peligro"),
            ],
        )
        self.page.show_dialog(dlg)

    # ==================================================================
    # Exportar
    # ==================================================================
    def _filas_export(self, detalle: dict) -> list:
        filas = []
        for p in detalle.get("pallets") or []:
            for l in p.get("lineas") or []:
                res = "NO_LLEGO" if p.get("estado") == "NO_LLEGO" else str(l.get("resultado") or "PENDIENTE")
                filas.append({
                    "OT": detalle.get("numero_ot"), "Pallet": p.get("lpn"), "LPN en Concepción": p.get("lpn_destino") or "",
                    "Estado pallet": NOMBRE_RESULTADO.get(p.get("estado"), p.get("estado")),
                    "SKU": l.get("sku"), "Descripción": l.get("descripcion"),
                    "Lote enviado": l.get("lote"), "Venc. enviado": l.get("vencimiento"),
                    "UN enviadas": _n(l.get("unidades")),
                    "Lote recibido": l.get("lote_recibido"), "Venc. recibido": l.get("vencimiento_recibido"),
                    "UN recibidas": _n(l.get("unidades_recibidas")) if res != "PENDIENTE" else None,
                    "Diferencia UN": (_n(l.get("unidades_recibidas")) - _n(l.get("unidades"))) if res != "PENDIENTE" else None,
                    "Resultado": NOMBRE_RESULTADO.get(res, res),
                    "Motivo": l.get("observacion") or (p.get("observacion") if res == "NO_LLEGO" else ""),
                    "Recibido por": p.get("usuario"), "Fecha": _fh(p.get("fecha")) if p.get("fecha") else "",
                })
        return filas

    def _guardar_excel(self, filas: list, nombre: str):
        if not filas:
            self._notificar("No hay datos para exportar.", "#D97706")
            return
        os.makedirs("reportes_traslados", exist_ok=True)
        ruta = os.path.join("reportes_traslados", f"{nombre}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
        pd.DataFrame(filas).to_excel(ruta, index=False)
        descargar_o_abrir_archivo(self.page, ruta)

    def _exportar_detalle(self):
        if self.detalle:
            self._guardar_excel(self._filas_export(self.detalle), f"Traslado_{self.detalle.get('numero_ot')}")

    def _exportar_diferencias(self):
        filas = []
        for t in self.traslados:
            if _n(t.get("pallets_con_diferencia")) == 0:
                continue
            try:
                det = self._rpc("wms_traslado_ccp_detalle", {"p_orden_id": int(t.get("orden_id"))}) or {}
            except Exception:
                continue
            filas += [f for f in self._filas_export(det) if f["Resultado"] not in ("Conforme", "Por recibir")]
        self._guardar_excel(filas, "Diferencias_traslados_CCP")

    # ==================================================================
    # Navegación (submenú del portal)
    # ==================================================================
    def sel_sub_recepcion_ccp(self, idx: int):
        if not self._validar_bodega():
            return
        self.vista_actual = 1 if idx == 1 else 0
        try:
            self.pestanas.data(self.vista_actual)
        except Exception:
            pass
        self.contenedor.content = self.sub_bandeja
        self.cargar_bandeja()

    def refrescar(self, e=None):
        if self.contenedor.content is self.sub_detalle and self.detalle:
            self.cargar_bandeja()
            self._recargar_detalle()
        else:
            self.cargar_bandeja()
