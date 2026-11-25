"""Recepción > Calendario de OC > vista «Por marca».

Las OC no se miran por fecha de creación (algunas llegan 4 a 6 meses después): se elige la marca
(ej. America Litter) y se ven TODAS sus OC abiertas en NetSuite, con la nota de la OC y si el WMS ya
tiene sus packing list. Una OC puede traer varios contenedores (un PL por contenedor): al abrir la OC
se ven sus contenedores con su estado, y al abrir un contenedor, lo que trae su PL contra lo recibido.
Requiere 48_oc_por_marca_contenedores.sql.
"""
import threading
from datetime import date, datetime

import flet as ft
from dependencias import (supabase, UI, ui_boton, ui_tarjeta, ui_tabla, ui_kpi, notificar_global,
                          formatear_fecha_hora_chile, descargar_o_abrir_archivo)

try:
    from conexion_erp import consultar_netsuite
    NETSUITE_OK = True
except Exception:
    consultar_netsuite = None
    NETSUITE_OK = False

# Estado de cada contenedor: color + texto (nunca solo color)
ESTADO_CONT = {
    "SIN_PL": ("#94A3B8", "Sin PL"),
    "PL_CARGADO": ("#38BDF8", "PL cargado · en camino"),
    "AGENDADO": ("#A78BFA", "Agendado"),
    "CITA_VENCIDA": ("#d03b3b", "Cita vencida"),
    "EN_RECEPCION": ("#fab219", "En recepción"),
    "RECIBIDO": ("#0ca30c", "Recibido"),
}
ESTADO_NS = {"SI": ("#0ca30c", "Sí"), "PARCIAL": ("#fab219", "Parcial"), "NO": ("#d03b3b", "No"),
             "SIN_DATO": ("#94A3B8", "Sin dato")}


def _t(txt, size=12, color=None, peso=None, **kw):
    return ft.Text("" if txt is None else str(txt), size=size, color=color or UI["texto"], weight=peso, **kw)


def _col(txt, numerica=False):
    return ft.DataColumn(ft.Text(txt, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"]), numeric=numerica)


def _chip(texto, color):
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=8, vertical=3), border_radius=4,
        bgcolor=ft.Colors.with_opacity(0.16, color), border=ft.Border.all(1, ft.Colors.with_opacity(0.5, color)),
        content=ft.Text(texto, size=11, weight=ft.FontWeight.W_600, color=UI["texto"]))


def _miles(v) -> str:
    try:
        return f"{int(float(v)):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def _fd(v) -> str:
    if not v:
        return "—"
    s = str(v)
    try:
        if len(s) <= 10:
            return date.fromisoformat(s[:10]).strftime("%d-%m-%Y")
        return formatear_fecha_hora_chile(s)
    except Exception:
        return s[:10]


def _err(ex) -> str:
    msg = str(getattr(ex, "message", None) or ex)
    if "PGRST202" in msg or "Could not find" in msg:
        return "falta ejecutar 48_oc_por_marca_contenedores.sql en Supabase"
    return msg.replace("WMS: ", "", 1)


class PanelOcPorMarca:
    def __init__(self, page: ft.Page, sincronizar_netsuite=None):
        self.page = page
        self.sincronizar_netsuite = sincronizar_netsuite
        self.marcas, self.ocs = [], []
        self.marca = None

        self.dd_marca = ft.Dropdown(
            label="Marca / proveedor", dense=True, width=320, options=[],
            bgcolor=UI["input"], border_color=UI["borde"], focused_border_color=UI["acento"],
            text_style=ft.TextStyle(size=12, color=UI["texto"]), border_radius=6,
            on_select=lambda e: self._elegir(self.dd_marca.value))
        self.txt_buscar = ft.TextField(
            hint_text="Buscar OC, nota o contenedor", dense=True, width=240, bgcolor=UI["input"], color=UI["texto"],
            border_color=UI["borde"], focused_border_color=UI["acento"], border_radius=6,
            prefix_icon=ft.Icons.SEARCH_ROUNDED, text_style=ft.TextStyle(size=12), on_change=lambda e: self._pintar_ocs())
        self.fila_marcas = ft.Row(spacing=8, wrap=True, run_spacing=8)

        self.k_oc, self.k_oc_det = ft.Text("0"), ft.Text("", size=11, color=UI["texto_3"])
        self.k_pl, self.k_pl_det = ft.Text("0"), ft.Text("OC con PL en el WMS", size=11, color=UI["texto_3"])
        self.k_cont, self.k_cont_det = ft.Text("0"), ft.Text("", size=11, color=UI["texto_3"])
        self.k_vieja, self.k_vieja_det = ft.Text("—"), ft.Text("días de la OC abierta más antigua", size=11, color=UI["texto_3"])

        self.tabla = ft.DataTable(
            heading_row_height=38, data_row_min_height=46, data_row_max_height=64, column_spacing=18,
            columns=[_col("OC"), _col("Creada"), _col("Días abierta", True), _col("Esperada"), _col("Estado NetSuite"),
                     _col("PL en WMS"), _col("Contenedores"), _col("Próxima cita"), _col("Unidades OC", True), _col("Nota")],
            rows=[])
        self.txt_vacio = _t("Elija una marca. Si no aparece ninguna, presione «Actualizar desde NetSuite».", 12.5, UI["texto_2"])

        self.vista = ft.Column([
            ft.Container(
                padding=14, border_radius=10, bgcolor=UI["card"], border=ft.Border.all(1, UI["borde"]),
                content=ft.Row([
                    ft.Column([_t("OC abiertas por marca", 18, peso=ft.FontWeight.W_700),
                               _t("Todas las OC que siguen abiertas en NetSuite, sin importar cuándo se crearon",
                                  12, UI["texto_2"])], spacing=2, tight=True),
                    ft.Row([self.dd_marca, self.txt_buscar,
                            ui_boton("Actualizar desde NetSuite", ft.Icons.CLOUD_SYNC_OUTLINED,
                                     lambda e: self._sincronizar(), "primario"),
                            ui_boton("Exportar", ft.Icons.DOWNLOAD_ROUNDED, lambda e: self._exportar(), "secundario")],
                           spacing=8, wrap=True, run_spacing=8),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True, run_spacing=8)),
            self.fila_marcas,
            ft.ResponsiveRow([
                ui_kpi(self.k_oc, "OC abiertas", ft.Icons.RECEIPT_LONG_OUTLINED, UI["acento"], self.k_oc_det),
                ui_kpi(self.k_pl, "Con packing list", ft.Icons.DESCRIPTION_OUTLINED, UI["primario"], self.k_pl_det),
                ui_kpi(self.k_cont, "Contenedores", ft.Icons.DIRECTIONS_BOAT_FILLED_OUTLINED, UI["primario"], self.k_cont_det),
                ui_kpi(self.k_vieja, "Más antigua", ft.Icons.HOURGLASS_BOTTOM_ROUNDED, UI["alerta"], self.k_vieja_det),
            ], spacing=12, run_spacing=12),
            ui_tarjeta(ft.Column([ui_tabla(self.tabla, 460), self.txt_vacio], spacing=8, tight=True),
                       titulo="OC abiertas de la marca",
                       subtitulo="Clic en una OC para ver sus contenedores; clic en un contenedor para ver lo que trae",
                       icono=ft.Icons.LIST_ALT_ROUNDED),
        ], spacing=14, tight=True)

    # ==================================================================
    def _notificar(self, t, c="#0284C7"):
        notificar_global(self.page, t, c)

    def _update(self):
        try:
            self.page.update()
        except Exception:
            pass

    def _sincronizar(self):
        if self.sincronizar_netsuite:
            self._notificar("Leyendo de NetSuite todas las OC abiertas...", "#0284C7")
            self.sincronizar_netsuite(silencioso=False)
        else:
            self._notificar("La conexión con NetSuite no está disponible aquí.", "#D97706")

    def refrescar(self, e=None):
        try:
            self.marcas = list(supabase.rpc("wms_oc_marcas", {}).execute().data or [])
        except Exception as ex:
            self.marcas = []
            self._notificar(f"No se pudieron leer las marcas: {_err(ex)}", "#B91C1C")
        nombres = [str(m.get("marca")) for m in self.marcas]
        self.dd_marca.options = [ft.DropdownOption(key=n, text=f"{n}  ({m.get('ocs')} OC)") for n, m in zip(nombres, self.marcas)]
        if self.marca not in nombres:
            preferida = next((n for n in nombres if "AMERICA" in n.upper() and "LITTER" in n.upper()), None)
            self.marca = preferida or (nombres[0] if nombres else None)
        self.dd_marca.value = self.marca
        self._pintar_marcas()
        self._cargar_ocs()

    def _elegir(self, marca):
        self.marca = marca
        self.dd_marca.value = marca
        self._pintar_marcas()
        self._cargar_ocs()

    def _pintar_marcas(self):
        chips = []
        for m in self.marcas[:14]:
            n = str(m.get("marca"))
            activa = n == self.marca
            chips.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=8), border_radius=8, ink=True,
                bgcolor=ft.Colors.with_opacity(0.18, UI["acento"]) if activa else UI["card_alt"],
                border=ft.Border.all(2 if activa else 1, UI["acento"] if activa else UI["borde"]),
                on_click=lambda e, x=n: self._elegir(x),
                content=ft.Column([
                    _t(n[:30], 12, peso=ft.FontWeight.W_700),
                    _t(f"{m.get('ocs')} OC abiertas · {m.get('con_pl') or 0} con PL", 11, UI["texto_2"]),
                ], spacing=1, tight=True)))
        self.fila_marcas.controls = chips

    def _cargar_ocs(self):
        if not self.marca:
            self.ocs = []
        else:
            try:
                self.ocs = list(supabase.rpc("wms_oc_por_marca", {"p_marca": self.marca}).execute().data or [])
            except Exception as ex:
                self.ocs = []
                self._notificar(f"No se pudieron leer las OC: {_err(ex)}", "#B91C1C")
        self._pintar_ocs()

    def _filtradas(self):
        q = (self.txt_buscar.value or "").strip().upper()
        if not q:
            return self.ocs
        return [o for o in self.ocs if q in " ".join(str(o.get(k) or "") for k in ("numero_oc", "tranid", "nota", "estado_ns")).upper()]

    def _pintar_ocs(self):
        filas = self._filtradas()
        self.k_oc.value = str(len(self.ocs))
        self.k_oc_det.value = f"{_miles(sum(float(o.get('unidades') or 0) for o in self.ocs))} unidades"
        self.k_pl.value = str(sum(1 for o in self.ocs if (o.get("con_pl") or 0) > 0 or o.get("en_wms")))
        tot_c = sum(int(o.get("contenedores") or 0) for o in self.ocs)
        self.k_cont.value = str(tot_c)
        self.k_cont_det.value = (f"{sum(int(o.get('recibidos') or 0) for o in self.ocs)} recibidos · "
                                 f"{sum(int(o.get('agendados') or 0) for o in self.ocs)} agendados")
        dias = [int(o.get("dias_abierta")) for o in self.ocs if o.get("dias_abierta") is not None]
        self.k_vieja.value = f"{max(dias)} d" if dias else "—"

        rows = []
        for o in filas:
            n_cont, n_pl = int(o.get("contenedores") or 0), int(o.get("con_pl") or 0)
            rec, enr = int(o.get("recibidos") or 0), int(o.get("en_recepcion") or 0)
            if n_pl:
                chip_pl = _chip(f"Sí · {n_pl} PL", "#0ca30c")
            elif o.get("en_wms"):
                chip_pl = _chip("OC cargada, sin PL", "#fab219")
            else:
                chip_pl = _chip("No", "#94A3B8")
            dias_ab = o.get("dias_abierta")
            nota = str(o.get("nota") or "")
            rows.append(ft.DataRow(
                on_select_change=lambda e, x=o: self._dialogo_oc(x),
                cells=[
                    ft.DataCell(_t(o.get("tranid") or o.get("numero_oc"), 12.5, UI["acento"], ft.FontWeight.W_700)),
                    ft.DataCell(_t(_fd(o.get("fecha_oc")), 11.5, UI["texto_2"])),
                    ft.DataCell(_t(f"{dias_ab} d" if dias_ab is not None else "—", 12,
                                   UI["peligro"] if (dias_ab or 0) > 120 else UI["texto"])),
                    ft.DataCell(_t(_fd(o.get("fecha_esperada")), 11.5, UI["texto_2"])),
                    ft.DataCell(_t(str(o.get("estado_ns") or "—")[:28], 11.5, UI["texto_2"])),
                    ft.DataCell(chip_pl),
                    ft.DataCell(_t(f"{n_cont} · {rec} recibidos" + (f" · {enr} recibiendo" if enr else "") if n_cont else "—", 12)),
                    ft.DataCell(_t(_fd(o.get("proxima_cita")), 11.5)),
                    ft.DataCell(_t(_miles(o.get("unidades")), 12)),
                    ft.DataCell(ft.Container(width=260, tooltip=nota or None,
                                             content=_t(nota[:70] + ("…" if len(nota) > 70 else ""), 11.5, UI["texto_2"]))),
                ]))
        self.tabla.rows = rows
        self.txt_vacio.visible = not rows
        self.txt_vacio.value = ("Esta marca no tiene OC abiertas." if self.marca else
                                "Elija una marca. Si no aparece ninguna, presione «Actualizar desde NetSuite».")
        self._update()

    # ==================================================================
    # Diálogos: OC → contenedores → detalle
    # ==================================================================
    def _cerrar(self, e=None):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def _dialogo(self, titulo, contenido, ancho=820):
        self.page.show_dialog(ft.AlertDialog(
            bgcolor=UI["card"], title=_t(titulo, 18, peso=ft.FontWeight.W_700),
            content=ft.Container(width=ancho, content=contenido),
            actions=[ui_boton("Cerrar", None, self._cerrar, "texto")], actions_alignment=ft.MainAxisAlignment.END))

    def _dialogo_oc(self, o):
        try:
            datos = supabase.rpc("wms_oc_contenedores", {"p_numero_oc": o.get("numero_oc")}).execute().data or {}
        except Exception as ex:
            self._notificar(f"No se pudo leer la OC: {_err(ex)}", "#B91C1C")
            return
        oc = datos.get("oc") or o
        conts = datos.get("contenedores") or []
        col_ns, txt_ns = ESTADO_NS.get(oc.get("cargada_ns") or o.get("cargada_ns"), ESTADO_NS["SIN_DATO"])

        filas = []
        for c in conts:
            col, nombre = ESTADO_CONT.get(c.get("estado"), ("#94A3B8", c.get("estado")))
            filas.append(ft.DataRow(
                on_select_change=lambda e, x=c: self._dialogo_contenedor(o, x),
                cells=[
                    ft.DataCell(_t(c.get("contenedor"), 12.5, UI["acento"], ft.FontWeight.W_700)),
                    ft.DataCell(_chip(nombre, col)),
                    ft.DataCell(_t(c.get("referencia_pl") or ("Sí" if c.get("tiene_pl") else "—"), 12)),
                    ft.DataCell(_t(_miles(c.get("unidades_pl")) if c.get("unidades_pl") is not None else "—", 12)),
                    ft.DataCell(_t(_miles(c.get("unidades_recibidas")), 12)),
                    ft.DataCell(_t(str(c.get("pallets") or 0), 12)),
                    ft.DataCell(_t((_fd(c.get("cita")) + (f" {c.get('hora_cita')}" if c.get("hora_cita") else ""))
                                   if c.get("cita") else "—", 11.5)),
                    ft.DataCell(_t(_fd(c.get("ultima_recepcion")) if c.get("ultima_recepcion") else "—", 11.5, UI["texto_2"])),
                ]))
        tabla_c = ft.DataTable(
            heading_row_height=36, data_row_min_height=40, data_row_max_height=48, column_spacing=16,
            columns=[_col("Contenedor"), _col("Estado"), _col("PL"), _col("UN en PL", True), _col("UN recibidas", True),
                     _col("Pallets", True), _col("Cita"), _col("Última recepción")],
            rows=filas)
        sin_cont = int(datos.get("recibido_sin_contenedor") or 0)

        lineas_ns = ft.Column([_t("Cargando líneas de NetSuite...", 11.5, UI["texto_3"])], spacing=4, tight=True)

        contenido = ft.Column([
            ft.Row([_t(oc.get("proveedor") or self.marca, 13, peso=ft.FontWeight.W_600),
                    _chip(f"NetSuite: {oc.get('estado_ns') or '—'}", "#64748B"),
                    _chip(f"Recibida en NetSuite: {txt_ns}", col_ns)], spacing=8, wrap=True),
            _t(f"Creada {_fd(oc.get('fecha_oc'))} · esperada {_fd(oc.get('fecha_esperada'))} · "
               f"{_miles(oc.get('unidades'))} unidades · {oc.get('lineas') or '—'} líneas", 12, UI["texto_2"]),
            ft.Container(
                padding=10, border_radius=8, bgcolor=UI["card_alt"], border=ft.Border.all(1, UI["borde"]),
                content=ft.Column([_t("Nota de la OC", 11, UI["texto_3"], ft.FontWeight.W_600),
                                   _t(oc.get("nota") or "Sin nota en NetSuite.", 12.5, selectable=True)], spacing=3, tight=True)),
            _t(f"Contenedores ({len(conts)})", 13, peso=ft.FontWeight.W_700),
            ui_tabla(tabla_c, 260) if conts else _t(
                "El WMS todavía no tiene contenedores para esta OC. Cargue el packing list de cada contenedor en "
                "Recepción (Cargar Packing List) o agéndelo en el Panel de recepciones.", 12, UI["alerta"]),
            *([_t(f"{_miles(sin_cont)} unidades se recibieron con la OC sin indicar el contenedor.", 11.5, UI["texto_3"])]
              if sin_cont else []),
            ft.Divider(height=8, color=UI["borde"]),
            _t("Líneas de la OC en NetSuite", 13, peso=ft.FontWeight.W_700),
            lineas_ns,
        ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO, height=560)
        self._dialogo(f"OC {oc.get('tranid') or o.get('numero_oc')}", contenido)
        self._cargar_lineas_ns(oc.get("ns_id") or o.get("ns_id"), lineas_ns)

    def _cargar_lineas_ns(self, ns_id, destino: ft.Column):
        if not (NETSUITE_OK and str(ns_id or "").split(".")[0].isdigit()):
            destino.controls = [_t("No disponible (sin conexión con NetSuite en este equipo).", 11.5, UI["texto_3"])]
            self._update()
            return
        ns = str(ns_id).split(".")[0]

        def trabajo():
            base = ("SELECT BUILTIN.DF(tl.item) AS articulo, ABS(tl.quantity) AS pedida, {extra} tl.memo AS nota "
                    "FROM transactionline tl WHERE tl.transaction = {ns} AND tl.mainline = 'F' AND tl.item IS NOT NULL "
                    "ORDER BY tl.linesequencenumber")
            df = None
            try:
                df = consultar_netsuite(base.format(extra="tl.quantityshiprecv AS recibida,", ns=ns))
                if df is None:
                    df = consultar_netsuite(base.format(extra="", ns=ns))
            except Exception:
                df = None
            if df is None:
                destino.controls = [_t("No se pudieron leer las líneas en NetSuite.", 11.5, UI["alerta"])]
            elif not len(df):
                destino.controls = [_t("La OC no tiene líneas de artículos.", 11.5, UI["texto_3"])]
            else:
                tiene_rec = "recibida" in df.columns
                rows = []
                for r in df.to_dict("records"):
                    ped = r.get("pedida")
                    reci = r.get("recibida") if tiene_rec else None
                    rows.append(ft.DataRow(cells=[
                        ft.DataCell(_t(str(r.get("articulo") or "")[:48], 12)),
                        ft.DataCell(_t(_miles(ped), 12)),
                        ft.DataCell(_t(_miles(reci) if tiene_rec else "—", 12)),
                        ft.DataCell(_t(str(r.get("nota") or "")[:60] if str(r.get("nota") or "") not in ("None", "nan") else "",
                                       11.5, UI["texto_2"])),
                    ]))
                destino.controls = [ui_tabla(ft.DataTable(
                    heading_row_height=34, data_row_min_height=34, data_row_max_height=42, column_spacing=16,
                    columns=[_col("Artículo"), _col("Pedida", True), _col("Recibida en NetSuite", True), _col("Nota línea")],
                    rows=rows), 240)]
            self._update()

        threading.Thread(target=trabajo, daemon=True).start()

    def _dialogo_contenedor(self, o, c):
        try:
            datos = supabase.rpc("wms_oc_contenedor_detalle", {"p_numero_oc": o.get("numero_oc"),
                                                                "p_contenedor": c.get("contenedor")}).execute().data or {}
        except Exception as ex:
            self._notificar(f"No se pudo leer el contenedor: {_err(ex)}", "#B91C1C")
            return
        pl = datos.get("pl") or {}
        lineas = datos.get("lineas") or []
        col, nombre = ESTADO_CONT.get(c.get("estado"), ("#94A3B8", c.get("estado")))
        rows = []
        for l in lineas:
            dif = int(l.get("diferencia") or 0)
            rows.append(ft.DataRow(cells=[
                ft.DataCell(_t(l.get("sku"), 12.5, peso=ft.FontWeight.W_700)),
                ft.DataCell(_t(str(l.get("descripcion") or "")[:34], 11.5, UI["texto_2"])),
                ft.DataCell(_t(str(l.get("lotes_pl") or "—")[:22], 11.5)),
                ft.DataCell(_t(str(l.get("vencimientos_pl") or "—")[:22], 11.5)),
                ft.DataCell(_t(_miles(l.get("cajas_pl")) if l.get("cajas_pl") is not None else "—", 12)),
                ft.DataCell(_t(_miles(l.get("unidades_pl")) if l.get("unidades_pl") is not None else "Fuera del PL", 12,
                               UI["alerta"] if l.get("fuera_de_pl") else None)),
                ft.DataCell(_t(_miles(l.get("unidades_recibidas")), 12)),
                ft.DataCell(_t(str(l.get("lotes_recibidos") or "—")[:22], 11.5)),
                ft.DataCell(_t(f"{dif:+d}".replace(",", ".") if dif else "0", 12,
                               UI["peligro"] if dif < 0 and l.get("unidades_recibidas") else
                               UI["alerta"] if dif > 0 else UI["texto_2"], ft.FontWeight.W_600)),
            ]))
        tot_pl = sum(int(l.get("unidades_pl") or 0) for l in lineas)
        tot_rec = sum(int(l.get("unidades_recibidas") or 0) for l in lineas)
        contenido = ft.Column([
            ft.Row([_chip(nombre, col), _t(f"OC {o.get('tranid') or o.get('numero_oc')}", 12.5, UI["texto_2"]),
                    *([_t(f"PL {pl.get('referencia_pl')}", 12.5, UI["texto_2"])] if pl.get("referencia_pl") else [])],
                   spacing=10, wrap=True),
            *([ft.Container(padding=10, border_radius=8, bgcolor=UI["card_alt"], border=ft.Border.all(1, UI["borde"]),
                            content=ft.Column([_t("Nota del packing list", 11, UI["texto_3"], ft.FontWeight.W_600),
                                               _t(pl.get("nota"), 12.5, selectable=True)], spacing=3, tight=True))]
              if pl.get("nota") else []),
            _t(f"Trae {_miles(tot_pl)} UN según PL · recibidas {_miles(tot_rec)} UN · diferencia {tot_rec - tot_pl:+d}"
               .replace(",", "."), 12.5, peso=ft.FontWeight.W_600),
            ui_tabla(ft.DataTable(
                heading_row_height=36, data_row_min_height=38, data_row_max_height=46, column_spacing=14,
                columns=[_col("SKU"), _col("Descripción"), _col("Lote PL"), _col("Venc. PL"), _col("Cajas PL", True),
                         _col("UN PL", True), _col("UN recibidas", True), _col("Lotes recibidos"), _col("Dif.", True)],
                rows=rows), 380) if rows else _t("Este contenedor no tiene detalle de PL ni recepciones.", 12, UI["texto_2"]),
        ], spacing=10, tight=True)
        self._dialogo(f"Contenedor {c.get('contenedor')}", contenido, ancho=900)

    # ==================================================================
    def _exportar(self):
        if not self.ocs:
            self._notificar("No hay OC para exportar.", "#D97706")
            return
        try:
            import pandas as pd
            import os
            filas = []
            for o in self.ocs:
                try:
                    conts = (supabase.rpc("wms_oc_contenedores", {"p_numero_oc": o.get("numero_oc")}).execute().data or {}
                             ).get("contenedores") or []
                except Exception:
                    conts = []
                base = {"Marca": self.marca, "OC": o.get("tranid") or o.get("numero_oc"), "Creada": _fd(o.get("fecha_oc")),
                        "Días abierta": o.get("dias_abierta"), "Esperada": _fd(o.get("fecha_esperada")),
                        "Estado NetSuite": o.get("estado_ns"), "Unidades OC": o.get("unidades"), "Nota OC": o.get("nota")}
                if not conts:
                    filas.append({**base, "Contenedor": "", "Estado contenedor": "", "UN PL": None, "UN recibidas": None, "Cita": ""})
                for c in conts:
                    filas.append({**base, "Contenedor": c.get("contenedor"),
                                  "Estado contenedor": ESTADO_CONT.get(c.get("estado"), ("", c.get("estado")))[1],
                                  "UN PL": c.get("unidades_pl"), "UN recibidas": c.get("unidades_recibidas"),
                                  "Cita": _fd(c.get("cita")) if c.get("cita") else ""})
            carpeta = os.path.join(os.getcwd(), "reportes_recepcion")
            os.makedirs(carpeta, exist_ok=True)
            nombre = "".join(ch if ch.isalnum() else "_" for ch in str(self.marca))[:40]
            ruta = os.path.join(carpeta, f"OC_abiertas_{nombre}_{datetime.now():%Y%m%d_%H%M}.xlsx")
            pd.DataFrame(filas).to_excel(ruta, index=False)
            descargar_o_abrir_archivo(self.page, ruta)
        except Exception as ex:
            self._notificar(f"No se pudo exportar: {ex}", "#B91C1C")
