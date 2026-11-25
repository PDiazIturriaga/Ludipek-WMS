"""Recepción > OC por proveedor.

Se elige el proveedor (ej. VETPLUS) y se ven TODAS sus OC en un listado: creada, esperada, estado y
nota de NetSuite, si está recibida en NetSuite, y lo del Panel de recepciones (si llegó físicamente,
pallets y unidades, contenedores, cita y reporte de recepción). Al elegir el proveedor el WMS trae de
NetSuite sus OC de los últimos 24 meses. Una OC puede traer varios contenedores (un PL por contenedor):
al abrir la OC se ven sus contenedores y al abrir un contenedor, su PL contra lo recibido.
Requiere 48 y 49.
"""
import re
import threading
from datetime import date, datetime, timedelta

import flet as ft
from dependencias import (supabase, UI, ui_boton, ui_tarjeta, ui_tabla, ui_kpi, notificar_global,
                          formatear_fecha_hora_chile, descargar_o_abrir_archivo, obtener_bodega_activa)

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
ESTADO_FISICO = {"SI": ("#0ca30c", "Recibida"), "PARCIAL": ("#fab219", "Parcial"), "NO": ("#d03b3b", "No ha llegado")}
FILTROS = [("TODAS", "Todas"), ("SIN_RECIBIR", "No han llegado"), ("PARCIAL", "Recibidas parcial"),
           ("RECIBIDAS", "Recibidas"), ("FALTA_NS", "Llegaron y falta en NetSuite"), ("ABIERTAS", "Abiertas en NetSuite")]


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
        return "falta ejecutar 48_oc_por_marca_contenedores.sql y 49_oc_por_proveedor.sql en Supabase"
    return msg.replace("WMS: ", "", 1)


class PanelOcPorProveedor:
    def __init__(self, page: ft.Page, traer_de_netsuite=None):
        """traer_de_netsuite(proveedor, al_terminar): trae de NetSuite las OC del proveedor (Calendario de OC)."""
        self.page = page
        self.traer_de_netsuite = traer_de_netsuite
        self.proveedores, self.ocs = [], []
        self.proveedor = None
        self._traidos = set()           # proveedores ya leídos de NetSuite en esta sesión

        self.txt_prov = ft.TextField(
            label="Proveedor", hint_text="Escriba ej. vetplus", dense=True, width=300, bgcolor=UI["input"],
            color=UI["texto"], border_color=UI["borde"], focused_border_color=UI["acento"], border_radius=6,
            prefix_icon=ft.Icons.STOREFRONT_OUTLINED, text_style=ft.TextStyle(size=12),
            on_change=lambda e: self._pintar_sugerencias(), on_submit=lambda e: self._elegir_escrito())
        self.dd_filtro = ft.Dropdown(
            label="Mostrar", dense=True, width=230, value="TODAS",
            options=[ft.DropdownOption(key=k, text=t) for k, t in FILTROS],
            bgcolor=UI["input"], border_color=UI["borde"], focused_border_color=UI["acento"],
            text_style=ft.TextStyle(size=12, color=UI["texto"]), border_radius=6,
            on_select=lambda e: self._pintar_ocs())
        self.dd_desde = ft.Dropdown(
            label="Desde", dense=True, width=150, value="365",
            options=[ft.DropdownOption(key="90", text="3 meses"), ft.DropdownOption(key="180", text="6 meses"),
                     ft.DropdownOption(key="365", text="12 meses"), ft.DropdownOption(key="730", text="24 meses"),
                     ft.DropdownOption(key="0", text="Todo")],
            bgcolor=UI["input"], border_color=UI["borde"], focused_border_color=UI["acento"],
            text_style=ft.TextStyle(size=12, color=UI["texto"]), border_radius=6,
            on_select=lambda e: self._cargar_ocs())
        self.txt_buscar = ft.TextField(
            hint_text="Buscar OC o nota", dense=True, width=200, bgcolor=UI["input"], color=UI["texto"],
            border_color=UI["borde"], focused_border_color=UI["acento"], border_radius=6,
            prefix_icon=ft.Icons.SEARCH_ROUNDED, text_style=ft.TextStyle(size=12), on_change=lambda e: self._pintar_ocs())
        self.fila_sugerencias = ft.Row(spacing=8, wrap=True, run_spacing=8)
        self.lbl_estado = _t("", 11.5, UI["texto_3"])
        self.barra = ft.ProgressBar(visible=False, color=UI["acento"], bgcolor=UI["borde"])

        self.k_total, self.k_total_det = ft.Text("0"), ft.Text("", size=11, color=UI["texto_3"])
        self.k_llegaron, self.k_llegaron_det = ft.Text("0"), ft.Text("", size=11, color=UI["texto_3"])
        self.k_pend, self.k_pend_det = ft.Text("0"), ft.Text("", size=11, color=UI["texto_3"])
        self.k_ns, self.k_ns_det = ft.Text("0"), ft.Text("llegaron y no están recibidas en NetSuite", size=11, color=UI["texto_3"])

        self.tabla = ft.DataTable(
            heading_row_height=40, data_row_min_height=48, data_row_max_height=66, column_spacing=16,
            columns=[_col("OC"), _col("Creada"), _col("Esperada"), _col("Estado NetSuite"), _col("Llegó al WMS"),
                     _col("Recibida en NetSuite"), _col("Pallets", True), _col("UN recibidas / OC"), _col("Contenedores"),
                     _col("Cita"), _col("Reporte"), _col("Nota")],
            rows=[])
        self.txt_vacio = _t("Escriba el proveedor (ej. vetplus) y elíjalo.", 12.5, UI["texto_2"])

        self.vista = ft.Column([
            ft.Container(
                padding=14, border_radius=10, bgcolor=UI["card"], border=ft.Border.all(1, UI["borde"]),
                content=ft.Column([
                    ft.Row([
                        ft.Column([_t("OC por proveedor", 18, peso=ft.FontWeight.W_700),
                                   _t("Todas las OC del proveedor: si llegaron, si están recibidas en NetSuite y su nota",
                                      12, UI["texto_2"])], spacing=2, tight=True),
                        ft.Row([
                            ui_boton("Traer de NetSuite", ft.Icons.CLOUD_SYNC_OUTLINED, lambda e: self._traer(forzar=True), "primario"),
                            ui_boton("Exportar", ft.Icons.DOWNLOAD_ROUNDED, lambda e: self._exportar(), "secundario"),
                        ], spacing=8, wrap=True),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True, run_spacing=8),
                    ft.Row([self.txt_prov, self.dd_filtro, self.dd_desde, self.txt_buscar], spacing=8, wrap=True, run_spacing=8),
                    self.fila_sugerencias,
                    self.lbl_estado,
                    self.barra,
                ], spacing=10, tight=True)),
            ft.ResponsiveRow([
                ui_kpi(self.k_total, "OC del proveedor", ft.Icons.RECEIPT_LONG_OUTLINED, UI["acento"], self.k_total_det),
                ui_kpi(self.k_llegaron, "Llegaron al WMS", ft.Icons.MOVE_TO_INBOX_ROUNDED, UI["exito"], self.k_llegaron_det),
                ui_kpi(self.k_pend, "No han llegado", ft.Icons.SCHEDULE_ROUNDED, UI["alerta"], self.k_pend_det),
                ui_kpi(self.k_ns, "Falta en NetSuite", ft.Icons.CLOUD_OFF_OUTLINED, UI["peligro"], self.k_ns_det),
            ], spacing=12, run_spacing=12),
            ui_tarjeta(ft.Column([ui_tabla(self.tabla, 520), self.txt_vacio], spacing=8, tight=True),
                       titulo="OC del proveedor",
                       subtitulo="Clic en una OC: recepción física, contenedores, reporte y líneas de NetSuite",
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

    def refrescar(self, e=None):
        try:
            self.proveedores = list(supabase.rpc("wms_oc_proveedores", {}).execute().data or [])
        except Exception as ex:
            self.proveedores = []
            self.lbl_estado.value = f"No se pudo leer la lista de proveedores: {_err(ex)}"
        self._pintar_sugerencias()
        if self.proveedor:
            self._cargar_ocs()
        else:
            self._update()

    def _coincidencias(self):
        q = re.sub(r"\s+", " ", (self.txt_prov.value or "").strip().upper())
        if not q:
            return self.proveedores[:10]
        return [p for p in self.proveedores if q in str(p.get("proveedor") or "")][:12]

    def _pintar_sugerencias(self):
        chips = []
        for p in self._coincidencias():
            n = str(p.get("proveedor"))
            activo = n == self.proveedor
            chips.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=7), border_radius=8, ink=True,
                bgcolor=ft.Colors.with_opacity(0.18, UI["acento"]) if activo else UI["card_alt"],
                border=ft.Border.all(2 if activo else 1, UI["acento"] if activo else UI["borde"]),
                on_click=lambda e, x=n: self._elegir(x),
                content=ft.Column([
                    _t(n[:34], 12, peso=ft.FontWeight.W_700),
                    _t(f"{p.get('ocs')} OC · {p.get('abiertas') or 0} abiertas · última {_fd(p.get('ultima_oc'))}", 10.5, UI["texto_2"]),
                ], spacing=1, tight=True)))
        q = (self.txt_prov.value or "").strip()
        if q and len(q) >= 3:
            chips.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=7), border_radius=8, ink=True,
                bgcolor=UI["card_alt"], border=ft.Border.all(1, UI["borde"]),
                on_click=lambda e: self._buscar_en_netsuite(q),
                content=ft.Row([ft.Icon(ft.Icons.TRAVEL_EXPLORE_ROUNDED, size=16, color=UI["acento"]),
                                _t(f"Buscar «{q}» en NetSuite", 12, UI["acento"], ft.FontWeight.W_600)], spacing=6, tight=True)))
        self.fila_sugerencias.controls = chips
        self._update()

    def _elegir_escrito(self):
        c = self._coincidencias()
        if c and (self.txt_prov.value or "").strip():
            self._elegir(str(c[0].get("proveedor")))
        elif (self.txt_prov.value or "").strip():
            self._buscar_en_netsuite(self.txt_prov.value.strip())

    def _elegir(self, proveedor):
        self.proveedor = proveedor
        self.txt_prov.value = proveedor
        self._pintar_sugerencias()
        self._cargar_ocs()
        self._traer()

    def _buscar_en_netsuite(self, texto):
        """El proveedor aún no tiene OC en el WMS: se buscan en NetSuite por nombre."""
        self.proveedor = None
        self._traer(texto_busqueda=texto, forzar=True)

    def _traer(self, forzar=False, texto_busqueda=None):
        nombre = texto_busqueda or self.proveedor
        if not nombre:
            self._notificar("Elija o escriba un proveedor.", "#D97706")
            return
        if not self.traer_de_netsuite:
            self.lbl_estado.value = "La conexión con NetSuite no está disponible en este equipo: se muestra lo que tiene el WMS."
            self._update()
            return
        if not forzar and nombre in self._traidos:
            return
        self._traidos.add(nombre)
        self.barra.visible = True
        self.lbl_estado.value = f"Trayendo de NetSuite las OC de {nombre} (últimos 24 meses)..."
        self._update()

        def al_terminar(msg, encontrado=None):
            self.barra.visible = False
            self.lbl_estado.value = msg
            try:
                self.proveedores = list(supabase.rpc("wms_oc_proveedores", {}).execute().data or [])
            except Exception:
                pass
            if texto_busqueda and not self.proveedor:
                q = texto_busqueda.strip().upper()
                cand = [p for p in self.proveedores if q in str(p.get("proveedor") or "")]
                if encontrado:
                    cand = [p for p in self.proveedores if str(p.get("proveedor")) == encontrado] or cand
                if cand:
                    self.proveedor = str(cand[0].get("proveedor"))
                    self.txt_prov.value = self.proveedor
            self._pintar_sugerencias()
            self._cargar_ocs()

        self.traer_de_netsuite(nombre, al_terminar)

    def _cargar_ocs(self):
        if not self.proveedor:
            self.ocs = []
        else:
            dias = int(self.dd_desde.value or "365")
            desde = (date.today() - timedelta(days=dias)).isoformat() if dias else None
            try:
                self.ocs = list(supabase.rpc("wms_oc_por_proveedor", {"p_proveedor": self.proveedor,
                                                                       "p_desde": desde}).execute().data or [])
            except Exception as ex:
                self.ocs = []
                self._notificar(f"No se pudieron leer las OC: {_err(ex)}", "#B91C1C")
        self._pintar_ocs()

    def _filtradas(self):
        f = self.dd_filtro.value or "TODAS"
        q = (self.txt_buscar.value or "").strip().upper()
        out = []
        for o in self.ocs:
            fis, ns = o.get("recibido_fisico"), o.get("cargada_ns")
            if f == "SIN_RECIBIR" and fis != "NO":
                continue
            if f == "PARCIAL" and fis != "PARCIAL":
                continue
            if f == "RECIBIDAS" and fis != "SI":
                continue
            if f == "FALTA_NS" and not (fis in ("SI", "PARCIAL") and ns in ("NO", "SIN_DATO")):
                continue
            if f == "ABIERTAS" and not o.get("abierta"):
                continue
            if q and q not in " ".join(str(o.get(k) or "") for k in ("numero_oc", "tranid", "nota", "estado_ns")).upper():
                continue
            out.append(o)
        return out

    def _pintar_ocs(self):
        ocs = self.ocs
        llegaron = [o for o in ocs if o.get("recibido_fisico") in ("SI", "PARCIAL")]
        pend = [o for o in ocs if o.get("recibido_fisico") == "NO"]
        falta_ns = [o for o in llegaron if o.get("cargada_ns") in ("NO", "SIN_DATO")]
        self.k_total.value = str(len(ocs))
        self.k_total_det.value = f"{sum(1 for o in ocs if o.get('abierta'))} abiertas en NetSuite"
        self.k_llegaron.value = str(len(llegaron))
        self.k_llegaron_det.value = f"{sum(1 for o in llegaron if o.get('recibido_fisico') == 'PARCIAL')} parciales"
        self.k_pend.value = str(len(pend))
        atrasadas = [o for o in pend if o.get("fecha_esperada") and str(o.get("fecha_esperada"))[:10] < date.today().isoformat()]
        self.k_pend_det.value = f"{len(atrasadas)} con fecha esperada vencida"
        self.k_ns.value = str(len(falta_ns))

        rows = []
        for o in self._filtradas():
            col_f, txt_f = ESTADO_FISICO.get(o.get("recibido_fisico"), ESTADO_FISICO["NO"])
            col_n, txt_n = ESTADO_NS.get(o.get("cargada_ns"), ESTADO_NS["SIN_DATO"])
            if o.get("recepcion_ns_fecha"):
                txt_n += f" {_fd(o.get('recepcion_ns_fecha'))}"
            fecha_lleg = _fd(o.get("primera_recepcion")) if o.get("primera_recepcion") else ""
            n_cont = int(o.get("contenedores") or 0)
            rep = o.get("reporte_estado")
            nota = str(o.get("nota") or "")
            esperada_vencida = (o.get("recibido_fisico") == "NO" and o.get("fecha_esperada")
                                and str(o.get("fecha_esperada"))[:10] < date.today().isoformat())
            cita = o.get("proxima_cita") or o.get("ultima_cita")
            rows.append(ft.DataRow(
                on_select_change=lambda e, x=o: self._dialogo_oc(x),
                cells=[
                    ft.DataCell(ft.Column([_t(o.get("tranid") or o.get("numero_oc"), 12.5, UI["acento"], ft.FontWeight.W_700),
                                           *([_t("solo en el WMS", 10, UI["texto_3"])] if not o.get("en_netsuite") else [])],
                                          spacing=0, tight=True)),
                    ft.DataCell(_t(_fd(o.get("fecha_oc")), 11.5, UI["texto_2"])),
                    ft.DataCell(_t(_fd(o.get("fecha_esperada")), 11.5, UI["peligro"] if esperada_vencida else UI["texto_2"])),
                    ft.DataCell(_t(str(o.get("estado_ns") or "—")[:26], 11.5, UI["texto_2"])),
                    ft.DataCell(ft.Column([_chip(txt_f, col_f), *([_t(fecha_lleg, 10, UI["texto_3"])] if fecha_lleg else [])],
                                          spacing=2, tight=True)),
                    ft.DataCell(_chip(txt_n, col_n)),
                    ft.DataCell(_t(str(o.get("pallets") or 0), 12)),
                    ft.DataCell(_t(f"{_miles(o.get('unidades_recibidas') or 0)} / {_miles(o.get('unidades_oc'))}", 12)),
                    ft.DataCell(_t(f"{int(o.get('contenedores_recibidos') or 0)}/{n_cont} recibidos" if n_cont else "—", 11.5)),
                    ft.DataCell(_t(_fd(cita) if cita else "—", 11.5)),
                    ft.DataCell(_t({"ENVIADO": "Enviado", "PENDIENTE": "En cola", "ENVIANDO": "En cola", "ERROR": "Error"}.get(rep, "—"),
                                   11.5, UI["exito"] if rep == "ENVIADO" else UI["peligro"] if rep == "ERROR" else UI["texto_2"])),
                    ft.DataCell(ft.Container(width=240, tooltip=nota or None,
                                             content=_t(nota[:60] + ("…" if len(nota) > 60 else ""), 11.5, UI["texto_2"]))),
                ]))
        self.tabla.rows = rows
        self.txt_vacio.visible = not rows
        self.txt_vacio.value = ("No hay OC con ese filtro." if self.proveedor else
                                "Escriba el proveedor (ej. vetplus) y elíjalo.")
        self._update()

    # ==================================================================
    # Diálogos: OC (recepción física + contenedores + NetSuite) → contenedor
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
            ft.Row([_t(oc.get("proveedor") or o.get("proveedor") or self.proveedor, 13, peso=ft.FontWeight.W_600),
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
            _t("Recepción física (Panel de recepciones)", 13, peso=ft.FontWeight.W_700),
            self._bloque_recepcion(o),
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

    def _bloque_recepcion(self, o):
        col_f, txt_f = ESTADO_FISICO.get(o.get("recibido_fisico"), ESTADO_FISICO["NO"])
        rep = o.get("reporte_estado")
        filas = [
            ft.Row([_chip(f"Llegó al WMS: {txt_f}", col_f), _chip("Tiene OC: Sí", "#0ca30c"),
                    *([_chip("La OC no está en la copia de NetSuite", "#fab219")] if not o.get("en_netsuite") else [])],
                   spacing=8, wrap=True),
        ]
        if o.get("recibido_fisico") in ("SI", "PARCIAL"):
            dias = o.get("dias_creacion_a_llegada")
            filas.append(_t(
                f"{o.get('pallets') or 0} pallets · {_miles(o.get('cajas'))} cajas · {_miles(o.get('unidades_recibidas'))} de "
                f"{_miles(o.get('unidades_oc'))} UN · desde {_fd(o.get('primera_recepcion'))} hasta {_fd(o.get('ultima_recepcion'))}"
                + (f" · llegó {dias} días después de creada" if dias is not None else ""), 12))
            if rep == "ENVIADO":
                filas.append(_t(f"Reporte de recepción enviado {_fd(o.get('reporte_enviado_en'))} a {o.get('reporte_enviado_a') or ''}",
                                11.5, UI["exito"]))
            elif rep in ("PENDIENTE", "ENVIANDO"):
                filas.append(_t("Reporte de recepción en cola de envío.", 11.5, UI["alerta"]))
            else:
                filas.append(ft.Row([
                    _t("Reporte de recepción: " + ("con error" if rep == "ERROR" else "no enviado"), 11.5,
                       UI["peligro"] if rep == "ERROR" else UI["texto_2"]),
                    ft.TextButton("Finalizar y enviar reporte", on_click=lambda e: self._finalizar(o)),
                ], spacing=6, wrap=True))
        else:
            cita = o.get("proxima_cita")
            filas.append(_t(("Próxima cita: " + _fd(cita)) if cita else
                            "Todavía no llega nada de esta OC" + (f" (esperada {_fd(o.get('fecha_esperada'))})"
                                                                   if o.get("fecha_esperada") else "") + ".", 12, UI["texto_2"]))
        return ft.Column(filas, spacing=6, tight=True)

    def _finalizar(self, o):
        ids = o.get("asn_ids") or []
        if not ids:
            return
        try:
            res = supabase.rpc("wms_recepcion_finalizar", {
                "p_bodega": obtener_bodega_activa(self.page), "p_asn_id": ids[-1], "p_contenedor": None,
                "p_usuario": str(getattr(self.page, "usuario_actual", None) or "PC")}).execute().data or {}
        except Exception as ex:
            self._notificar(f"No se pudo: {_err(ex)}", "#B91C1C")
            return
        self._cerrar()
        self._notificar(f"Reporte en cola. Se envía a {res.get('destinatarios') or 0} destinatario(s).",
                        "#047857" if res.get("destinatarios") else "#B45309")
        self._cargar_ocs()

    # ==================================================================
    def _exportar(self):
        if not self.ocs:
            self._notificar("No hay OC para exportar.", "#D97706")
            return
        try:
            import pandas as pd
            import os
            filas = [{
                "Proveedor": o.get("proveedor"), "OC": o.get("tranid") or o.get("numero_oc"), "Creada": _fd(o.get("fecha_oc")),
                "Esperada": _fd(o.get("fecha_esperada")), "Estado NetSuite": o.get("estado_ns"),
                "Abierta en NetSuite": "Sí" if o.get("abierta") else "No",
                "Llegó al WMS": ESTADO_FISICO.get(o.get("recibido_fisico"), ("", ""))[1],
                "Primera recepción": _fd(o.get("primera_recepcion")) if o.get("primera_recepcion") else "",
                "Días creación a llegada": o.get("dias_creacion_a_llegada"),
                "Recibida en NetSuite": ESTADO_NS.get(o.get("cargada_ns"), ("", ""))[1],
                "Fecha recepción NetSuite": _fd(o.get("recepcion_ns_fecha")) if o.get("recepcion_ns_fecha") else "",
                "Pallets": o.get("pallets"), "UN recibidas": o.get("unidades_recibidas"), "UN OC": o.get("unidades_oc"),
                "Contenedores": o.get("contenedores"), "Contenedores recibidos": o.get("contenedores_recibidos"),
                "Reporte": o.get("reporte_estado") or "", "Nota": o.get("nota"),
            } for o in self._filtradas()]
            carpeta = os.path.join(os.getcwd(), "reportes_recepcion")
            os.makedirs(carpeta, exist_ok=True)
            nombre = "".join(ch if ch.isalnum() else "_" for ch in str(self.proveedor))[:40]
            ruta = os.path.join(carpeta, f"OC_{nombre}_{datetime.now():%Y%m%d_%H%M}.xlsx")
            pd.DataFrame(filas).to_excel(ruta, index=False)
            descargar_o_abrir_archivo(self.page, ruta)
        except Exception as ex:
            self._notificar(f"No se pudo exportar: {ex}", "#B91C1C")


PanelOcPorMarca = PanelOcPorProveedor      # nombre anterior
