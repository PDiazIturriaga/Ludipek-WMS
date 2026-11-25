"""Recepción > Calendario de OC.

Muestra en un calendario las órdenes de compra que van cayendo en NetSuite y mide los tiempos:
creada en NetSuite -> llegó (primer pallet recibido) -> cerrada en el WMS, y contra la fecha
esperada de NetSuite. Las OC se traen solas de NetSuite (al abrir, si la última lectura tiene más
de 30 minutos) o con "Actualizar desde NetSuite". Requiere 45_calendario_oc.sql.

Vista «Por marca» (m1_oc_marca, script 48): todas las OC abiertas de una marca, sin importar la fecha
de creación, con sus contenedores (un PL por contenedor) y el detalle de cada uno.
"""
import calendar
import os
import threading
from datetime import date, datetime, timedelta

import pandas as pd
import flet as ft
import re
from dependencias import (supabase, UI, ui_boton, ui_tarjeta, ui_tabla, ui_kpi, notificar_global,
                          formatear_fecha_hora_chile, descargar_o_abrir_archivo, obtener_bodega_activa)
from modulos.m1_oc_marca import PanelOcPorProveedor

# OC abiertas en NetSuite: por aprobar, pendiente de recepción, parcialmente recibida, parcial/por facturar
FILTRO_OC_ABIERTAS = "t.status IN ('PurchOrd:A', 'PurchOrd:B', 'PurchOrd:D', 'PurchOrd:E')"

try:
    from conexion_erp import consultar_netsuite
    import conexion_erp
    NETSUITE_OK = True
except Exception:
    consultar_netsuite = None
    conexion_erp = None
    NETSUITE_OK = False

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre",
         "Octubre", "Noviembre", "Diciembre"]
DIAS = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sá", "Do"]

# Estados: color + texto (nunca solo color)
ESTADOS = {
    "POR_LLEGAR": ("#38BDF8", "Por llegar"),
    "ATRASADA": ("#d03b3b", "Atrasada"),
    "RECIBIENDO": ("#fab219", "Recibiendo"),
    "CERRADA": ("#0ca30c", "Cerrada"),
}
COLOR_CITA = "#A78BFA"


def _valor(v):
    """Texto limpio para la base: los vacíos de pandas (NaN, NaT, None) van como null, no como 'nan'."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    t = str(v).strip()
    if t.lower() in ("", "nan", "nat", "none", "null"):
        return None
    if t.endswith(".0") and t[:-2].isdigit():      # ids y cantidades que pandas dejó como float
        t = t[:-2]
    return t


def _num_oc(txt) -> str:
    return re.sub(r"^(OC|PO)[\s\-#]*", "", str(txt or "").strip().upper())


VISTAS = [("creada_en", "Creación en NetSuite"), ("fecha_esperada", "Fecha esperada"), ("llego_en", "Llegada a bodega")]


def _n(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dia(valor):
    """Fecha (date) de un valor ISO de Supabase; si trae hora, en hora de Chile."""
    if not valor:
        return None
    txt = str(valor)
    try:
        if len(txt) <= 10:
            return date.fromisoformat(txt[:10])
        return _a_chile(txt).date()
    except Exception:
        try:
            return date.fromisoformat(txt[:10])
        except Exception:
            return None


def _a_chile(txt: str) -> datetime:
    from zoneinfo import ZoneInfo
    dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo("America/Santiago")) if dt.tzinfo else dt


def _fd(valor) -> str:
    """dd-mm-aaaa (con hora si la trae)."""
    if not valor:
        return "—"
    if len(str(valor)) <= 10:
        d = _dia(valor)
        return d.strftime("%d-%m-%Y") if d else str(valor)
    return formatear_fecha_hora_chile(valor)


def _dias(v) -> str:
    x = _n(v)
    if x is None:
        return "—"
    return f"{x:.1f}".replace(".", ",") + " d"


def _promedio(valores):
    xs = [x for x in (_n(v) for v in valores) if x is not None and x >= 0]
    return (sum(xs) / len(xs)) if xs else None


def _chip(texto: str, color: str):
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=8, vertical=3), border_radius=4,
        bgcolor=ft.Colors.with_opacity(0.16, color), border=ft.Border.all(1, ft.Colors.with_opacity(0.5, color)),
        content=ft.Text(texto, size=11, weight=ft.FontWeight.W_600, color=UI["texto"]),
    )


def _col(txt: str, numerica: bool = False):
    return ft.DataColumn(ft.Text(txt, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"]), numeric=numerica)


def _t(txt, size=12, color=None, peso=None):
    return ft.Text(str(txt if txt is not None else ""), size=size, color=color or UI["texto"], weight=peso)


class PanelCalendarioOc:
    def __init__(self, page: ft.Page):
        self.page = page
        hoy = date.today()
        self.anio, self.mes = hoy.year, hoy.month
        self.vista_fecha = "creada_en"
        self.filas = []
        self.citas = []                # agenda de contenedores (script 46)
        self.despues_de_sincronizar = None     # ej. refrescar el Panel de recepciones
        self.sincronizando = False
        self._meses_leidos = set()     # meses ya traídos de NetSuite en esta sesión

        self.lbl_mes = ft.Text("", size=18, weight=ft.FontWeight.W_700, color=UI["texto"])
        self.lbl_sync = ft.Text("", size=11.5, color=UI["texto_3"])
        self.dd_vista = ft.Dropdown(
            label="Ubicar cada OC en el día de", dense=True, width=240, value=self.vista_fecha,
            options=[ft.DropdownOption(key=k, text=t) for k, t in VISTAS],
            bgcolor=UI["input"], border_color=UI["borde"], focused_border_color=UI["acento"],
            text_style=ft.TextStyle(size=12, color=UI["texto"]), border_radius=6,
            on_select=lambda e: self._cambiar_vista(),
        )
        self.txt_buscar = ft.TextField(
            hint_text="Buscar OC o proveedor", dense=True, width=210, bgcolor=UI["input"], color=UI["texto"],
            border_color=UI["borde"], focused_border_color=UI["acento"], border_radius=6,
            prefix_icon=ft.Icons.SEARCH_ROUNDED, text_style=ft.TextStyle(size=12),
            on_change=lambda e: self._pintar(),
        )
        self.btn_sync = ui_boton("Actualizar desde NetSuite", ft.Icons.CLOUD_SYNC_OUTLINED, lambda e: self.sincronizar(),
                                 "primario")

        # Indicadores
        self.k_total, self.k_total_det = ft.Text("0"), ft.Text("", size=11, color=UI["texto_3"])
        self.k_cl, self.k_cl_det = ft.Text("—"), ft.Text("creada en NetSuite → llegó", size=11, color=UI["texto_3"])
        self.k_lc, self.k_lc_det = ft.Text("—"), ft.Text("llegó → cerrada en el WMS", size=11, color=UI["texto_3"])
        self.k_tiempo, self.k_tiempo_det = ft.Text("—"), ft.Text("llegaron hasta la fecha esperada", size=11, color=UI["texto_3"])
        self.k_atr, self.k_atr_det = ft.Text("0"), ft.Text("", size=11, color=UI["texto_3"])
        fila_kpis = ft.ResponsiveRow([
            ui_kpi(self.k_total, "OC del mes", ft.Icons.RECEIPT_LONG_OUTLINED, UI["acento"], self.k_total_det),
            ui_kpi(self.k_cl, "Promedio hasta llegar", ft.Icons.LOCAL_SHIPPING_OUTLINED, UI["primario"], self.k_cl_det),
            ui_kpi(self.k_lc, "Promedio hasta cerrar", ft.Icons.INVENTORY_2_OUTLINED, UI["primario"], self.k_lc_det),
            ui_kpi(self.k_tiempo, "A tiempo", ft.Icons.VERIFIED_ROUNDED, UI["exito"], self.k_tiempo_det),
            ui_kpi(self.k_atr, "Atrasadas sin llegar", ft.Icons.REPORT_PROBLEM_OUTLINED, UI["peligro"], self.k_atr_det),
        ], spacing=12, run_spacing=12)

        self.grilla = ft.Column(spacing=4, tight=True)
        leyenda = ft.Row([_chip(t, c) for c, t in ESTADOS.values()] + [_chip("Cita de contenedor", COLOR_CITA)],
                         spacing=8, wrap=True)

        self.tabla = ft.DataTable(
            heading_row_height=38, data_row_min_height=40, data_row_max_height=52,
            columns=[_col("OC"), _col("Proveedor"), _col("Estado"), _col("Creada"), _col("Esperada"), _col("Llegó"),
                     _col("Cerrada"), _col("Creada → llegó", True), _col("Llegó → cerrada", True), _col("Atraso", True)],
            rows=[],
        )
        self.txt_vacio = ft.Text("No hay OC en este mes. Presione «Actualizar desde NetSuite».", size=12.5,
                                 color=UI["texto_2"], visible=False)

        self.modo = "MARCA"
        self.panel_marca = PanelOcPorProveedor(page, self.traer_oc_proveedor)
        self.btn_modo_marca = ft.Container()
        self.btn_modo_cal = ft.Container()
        self.selector_modo = ft.Row([self.btn_modo_marca, self.btn_modo_cal], spacing=8)

        self.vista_calendario = ft.Column([
            ft.Container(
                padding=14, border_radius=10, bgcolor=UI["card"], border=ft.Border.all(1, UI["borde"]),
                content=ft.Row([
                    ft.Row([
                        ft.IconButton(icon=ft.Icons.CHEVRON_LEFT_ROUNDED, icon_color=UI["acento"], tooltip="Mes anterior",
                                      on_click=lambda e: self._mover_mes(-1)),
                        self.lbl_mes,
                        ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT_ROUNDED, icon_color=UI["acento"], tooltip="Mes siguiente",
                                      on_click=lambda e: self._mover_mes(1)),
                        ui_boton("Hoy", None, lambda e: self._ir_hoy(), "texto"),
                    ], spacing=4, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Row([self.dd_vista, self.txt_buscar, self.btn_sync,
                            ui_boton("Exportar", ft.Icons.DOWNLOAD_ROUNDED, lambda e: self._exportar(), "secundario")],
                           spacing=8, wrap=True, run_spacing=8),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True, run_spacing=8,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ),
            self.lbl_sync,
            fila_kpis,
            ui_tarjeta(ft.Column([leyenda, self.grilla], spacing=10, tight=True), titulo="Calendario de órdenes de compra",
                       subtitulo="Clic en una OC para ver su línea de tiempo; clic en el día para ver todas",
                       icono=ft.Icons.CALENDAR_MONTH_OUTLINED),
            ui_tarjeta(ft.Column([ui_tabla(self.tabla, 420), self.txt_vacio], spacing=8, tight=True),
                       titulo="OC del mes y sus tiempos", icono=ft.Icons.TIMER_OUTLINED),
        ], spacing=14, tight=True, visible=False)
        self.vista = ft.Column([self.selector_modo, self.panel_marca.vista, self.vista_calendario], spacing=14, tight=True)
        self._pintar_modo()

    def _boton_modo(self, clave, texto, icono):
        activo = self.modo == clave
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=14, vertical=8), border_radius=8, ink=True,
            bgcolor=ft.Colors.with_opacity(0.18, UI["acento"]) if activo else UI["card_alt"],
            border=ft.Border.all(1, UI["acento"] if activo else UI["borde"]),
            on_click=lambda e: self._cambiar_modo(clave),
            content=ft.Row([ft.Icon(icono, size=18, color=UI["acento"]),
                            ft.Text(texto, size=12.5, weight=ft.FontWeight.W_600, color=UI["texto"])], spacing=6, tight=True))

    def _pintar_modo(self):
        self.selector_modo.controls = [
            self._boton_modo("MARCA", "OC por proveedor (listado)", ft.Icons.LIST_ALT_ROUNDED),
            self._boton_modo("CALENDARIO", "Calendario y tiempos", ft.Icons.CALENDAR_MONTH_OUTLINED),
        ]
        self.panel_marca.vista.visible = self.modo == "MARCA"
        self.vista_calendario.visible = self.modo == "CALENDARIO"

    def _cambiar_modo(self, modo):
        self.modo = modo
        self._pintar_modo()
        self.refrescar(forzar=True)

    # ==================================================================
    # Datos
    # ==================================================================
    def _notificar(self, texto, color="#0284C7"):
        notificar_global(self.page, texto, color)

    def _rango_mes(self):
        ini = date(self.anio, self.mes, 1)
        fin = date(self.anio, self.mes, calendar.monthrange(self.anio, self.mes)[1])
        return ini, fin

    def refrescar(self, forzar: bool = False):
        if self.modo == "MARCA":           # listado por proveedor: trae de NetSuite al elegir el proveedor
            self.panel_marca.refrescar()
            return
        ini, fin = self._rango_mes()
        self.lbl_mes.value = f"{MESES[self.mes - 1]} {self.anio}"
        try:
            self.filas = list(supabase.rpc("wms_oc_calendario", {"p_desde": ini.isoformat(),
                                                                 "p_hasta": fin.isoformat()}).execute().data or [])
        except Exception as ex:
            self.filas = []
            msg = str(getattr(ex, "message", None) or ex)
            if "wms_oc_calendario" in msg or "PGRST202" in msg:
                msg = "falta ejecutar 45_calendario_oc.sql en Supabase"
            self._notificar(f"No se pudo leer el calendario: {msg}", "#B91C1C")
        try:
            self.citas = list(supabase.rpc("wms_agenda_rango", {"p_bodega": obtener_bodega_activa(self.page),
                                                                "p_desde": ini.isoformat(), "p_hasta": fin.isoformat()}
                                           ).execute().data or [])
        except Exception:
            self.citas = []            # sin script 46 el calendario funciona igual
        ultima = None
        try:
            ultima = supabase.rpc("wms_oc_ultima_sincronizacion", {}).execute().data
        except Exception:
            pass
        self.lbl_sync.value = (f"Última lectura de NetSuite: {formatear_fecha_hora_chile(ultima)}" if ultima
                               else "Todavía no se han leído OC desde NetSuite.")
        self._pintar()
        # Lectura automática: si la última tiene más de 30 minutos
        if forzar is False and NETSUITE_OK and not self.sincronizando:
            vieja = True
            try:
                vieja = (datetime.now().astimezone() - datetime.fromisoformat(str(ultima).replace("Z", "+00:00"))) \
                    > timedelta(minutes=30) if ultima else True
            except Exception:
                vieja = True
            if vieja or (self.anio, self.mes) not in self._meses_leidos:
                self.sincronizar(silencioso=True)

    # Formas de saber si una OC tiene recepción en NetSuite, de la más completa a la más simple.
    # Se recuerda la que funcionó (NetSuite responde distinto según la cuenta y los permisos).
    _forma_recepcion_ns = None

    def _revisar_recepciones_ns(self, ids: list) -> list:
        """[{ns_id, recepciones, fecha}] para cada OC de `ids` (0 recepciones si no tiene)."""
        consultas = {
            # 1) recepciones de artículos enlazadas a la OC desde su línea principal (trae la fecha)
            "ENLACE_LINEA": """
                SELECT tl.createdfrom AS po_id, COUNT(DISTINCT t.id) AS recepciones,
                       TO_CHAR(MIN(t.trandate), 'YYYY-MM-DD') AS fecha
                FROM transaction t INNER JOIN transactionline tl ON tl.transaction = t.id
                WHERE t.type = 'ItemRcpt' AND tl.mainline = 'T' AND tl.createdfrom IN ({ids})
                GROUP BY tl.createdfrom""",
            # 2) cantidad recibida en las líneas de la OC (sin fecha)
            "CANTIDAD_RECIBIDA": """
                SELECT tl.transaction AS po_id,
                       CASE WHEN SUM(NVL(tl.quantityshiprecv, 0)) > 0 THEN 1 ELSE 0 END AS recepciones
                FROM transactionline tl
                WHERE tl.transaction IN ({ids}) AND tl.mainline = 'F' AND tl.item IS NOT NULL
                GROUP BY tl.transaction""",
            # 3) enlace en la cabecera
            "ENLACE_CABECERA": """
                SELECT t.createdfrom AS po_id, COUNT(*) AS recepciones, MIN(t.trandate) AS fecha
                FROM transaction t
                WHERE t.type = 'ItemRcpt' AND t.createdfrom IN ({ids})
                GROUP BY t.createdfrom""",
        }
        orden = list(consultas)
        if PanelCalendarioOc._forma_recepcion_ns in consultas:
            orden.remove(PanelCalendarioOc._forma_recepcion_ns)
            orden.insert(0, PanelCalendarioOc._forma_recepcion_ns)
        marcas, ultimo_error = [], ""
        for i in range(0, len(ids), 100):
            lote = ids[i:i + 100]
            dfr = None
            for forma in list(orden):
                dfr = consultar_netsuite(consultas[forma].format(ids=",".join(lote)))
                if dfr is not None:
                    PanelCalendarioOc._forma_recepcion_ns = forma
                    orden.remove(forma)
                    orden.insert(0, forma)
                    break
                ultimo_error = getattr(conexion_erp, "ULTIMO_ERROR_NETSUITE", "") or "sin respuesta"
                orden.remove(forma)          # esa forma no sirve en esta cuenta: no se reintenta
                if not orden:
                    break
            if dfr is None:
                raise RuntimeError(ultimo_error)
            por_po = {_valor(r.get("po_id")): r for r in dfr.to_dict("records")} if len(dfr) else {}
            for pid in lote:
                r = por_po.get(pid) or {}
                fecha = _valor(r.get("fecha"))
                if fecha:
                    try:      # solo AAAA-MM-DD (dd/mm o mm/dd depende de la cuenta: mejor sin fecha que una equivocada)
                        fecha = date.fromisoformat(fecha[:10]).isoformat()
                    except ValueError:
                        fecha = None
                marcas.append({"ns_id": pid, "recepciones": _valor(r.get("recepciones")) or "0", "fecha": fecha})
        return marcas

    def traer_oc_proveedor(self, nombre: str, al_terminar):
        """Trae de NetSuite las OC del proveedor (últimos 24 meses), con unidades y si tienen recepción.
        Corre en segundo plano y al final llama al_terminar(mensaje, nombre_en_netsuite)."""
        if not NETSUITE_OK:
            al_terminar("La conexión con NetSuite no está disponible en este equipo: se muestra lo que tiene el WMS.")
            return

        def trabajo():
            q = re.sub(r"\s+", " ", str(nombre or "").strip().upper()).replace("'", "''")
            desde = (date.today() - timedelta(days=730)).isoformat()
            rango = f"t.trandate >= TO_DATE('{desde}', 'YYYY-MM-DD')"
            filtros = [
                f"UPPER(BUILTIN.DF(t.entity)) LIKE '%{q}%' AND {rango}",
                f"t.entity IN (SELECT v.id FROM vendor v WHERE UPPER(v.companyname) LIKE '%{q}%' "
                f"OR UPPER(v.entityid) LIKE '%{q}%') AND {rango}",
            ]
            df = None
            for filtro in filtros:
                for completa in (True, False):
                    df = consultar_netsuite(self._consulta_ns(date.today(), date.today(), completa, filtro))
                    if df is not None:
                        break
                if df is not None:
                    break
            if df is None:
                err = getattr(conexion_erp, "ULTIMO_ERROR_NETSUITE", "") or "sin respuesta"
                al_terminar(f"No se pudo leer NetSuite ({str(err)[:140]}). Se muestra lo que tiene el WMS.")
                return
            filas = df.where(pd.notna(df), None).to_dict("records") if len(df) else []
            if not filas:
                al_terminar(f"NetSuite no tiene OC de «{nombre}» en los últimos 24 meses.")
                return
            ids = sorted({_valor(f.get("ns_id")) for f in filas if (_valor(f.get("ns_id")) or "").isdigit()})
            try:
                por_id = {}
                for i in range(0, len(ids), 200):
                    dfu = consultar_netsuite(f"""
                        SELECT tl.transaction AS ns_id, SUM(ABS(tl.quantity)) AS unidades, COUNT(*) AS lineas
                        FROM transactionline tl
                        WHERE tl.mainline = 'F' AND tl.item IS NOT NULL AND tl.transaction IN ({",".join(ids[i:i + 200])})
                        GROUP BY tl.transaction""")
                    if dfu is not None and len(dfu):
                        por_id.update({_valor(r.get("ns_id")): r for r in dfu.to_dict("records")})
                for f in filas:
                    r = por_id.get(_valor(f.get("ns_id")))
                    if r:
                        f["unidades"], f["lineas"] = r.get("unidades"), r.get("lineas")
            except Exception:
                pass
            try:
                limpio = [{k: _valor(v) for k, v in f.items()} for f in filas]
                res = supabase.rpc("wms_oc_sincronizar", {"p_filas": limpio}).execute().data or {}
            except Exception as ex:
                al_terminar(f"No se pudieron guardar las OC: {getattr(ex, 'message', None) or ex}")
                return
            msg_r = ""
            try:
                marcas = self._revisar_recepciones_ns(ids)
                if marcas:
                    supabase.rpc("wms_oc_marcar_recepcion_ns", {"p_filas": marcas}).execute()
            except Exception as ex_r:
                msg_r = f" (no se pudo revisar la recepción en NetSuite: {str(ex_r)[:120]})"
            nombres = [str(f.get("proveedor") or "").strip().upper() for f in filas if f.get("proveedor")]
            principal = max(set(nombres), key=nombres.count) if nombres else None
            al_terminar(f"NetSuite: {res.get('leidas', 0)} OC de {principal or nombre} ({res.get('nuevas', 0)} nuevas) · "
                        f"{datetime.now():%H:%M}.{msg_r}", re.sub(r"\s+", " ", principal) if principal else None)

        threading.Thread(target=trabajo, daemon=True).start()

    def _consulta_ns(self, ini: date, fin: date, completa: bool, filtro: str = None) -> str:
        extra = ("TO_CHAR(t.createddate, 'YYYY-MM-DD HH24:MI:SS') AS creada_en, "
                 "TO_CHAR(t.duedate, 'YYYY-MM-DD') AS fecha_esperada, "
                 "BUILTIN.DF(t.location) AS ubicacion, ") if completa else ""
        if not filtro:
            filtro = (f"t.trandate >= TO_DATE('{ini.isoformat()}', 'YYYY-MM-DD') "
                      f"AND t.trandate <= TO_DATE('{fin.isoformat()}', 'YYYY-MM-DD')")
        return f"""
            SELECT t.id AS ns_id, t.tranid AS tranid, TO_CHAR(t.trandate, 'YYYY-MM-DD') AS fecha_oc, {extra}
                   BUILTIN.DF(t.entity) AS proveedor, BUILTIN.DF(t.status) AS estado_ns, t.memo AS nota
            FROM transaction t
            WHERE t.type = 'PurchOrd'
              AND {filtro}
            ORDER BY t.trandate
        """

    def sincronizar(self, silencioso: bool = False):
        if self.sincronizando:
            return
        if not NETSUITE_OK:
            if not silencioso:
                self._notificar("La conexión con NetSuite no está activa en este equipo (faltan las credenciales).", "#D97706")
            return
        self.sincronizando = True
        self.btn_sync.disabled = True
        try:
            self.page.update()
        except Exception:
            pass

        def trabajo():
            msg, color = "", "#047857"
            try:
                ini, fin = self._rango_mes()
                desde = ini - timedelta(days=90)     # OC creadas antes que pueden llegar este mes
                df = consultar_netsuite(self._consulta_ns(desde, fin, True))
                if df is None:                       # campo no disponible en la cuenta: lectura básica
                    df = consultar_netsuite(self._consulta_ns(desde, fin, False))
                if df is None:
                    raise RuntimeError(getattr(conexion_erp, "ULTIMO_ERROR_NETSUITE", "") or "sin respuesta de NetSuite")
                filas = df.where(pd.notna(df), None).to_dict("records") if len(df) else []
                # TODAS las OC abiertas (pueden ser de hace meses): quedan marcadas como abiertas
                abiertas = None
                try:
                    dfa = consultar_netsuite(self._consulta_ns(ini, fin, True, FILTRO_OC_ABIERTAS))
                    if dfa is None:
                        dfa = consultar_netsuite(self._consulta_ns(ini, fin, False, FILTRO_OC_ABIERTAS))
                    if dfa is not None:
                        abiertas = dfa.where(pd.notna(dfa), None).to_dict("records") if len(dfa) else []
                        ids_ventana = {_valor(f.get("ns_id")) for f in filas}
                        filas += [f for f in abiertas if _valor(f.get("ns_id")) not in ids_ventana]
                except Exception as ex_a:
                    print(f"[CALENDARIO OC] OC abiertas: {ex_a}")
                # Unidades y líneas por OC
                try:
                    dfl = consultar_netsuite(f"""
                        SELECT tl.transaction AS ns_id, SUM(ABS(tl.quantity)) AS unidades, COUNT(*) AS lineas
                        FROM transactionline tl INNER JOIN transaction t ON t.id = tl.transaction
                        WHERE t.type = 'PurchOrd' AND tl.mainline = 'F' AND tl.item IS NOT NULL
                          AND t.trandate >= TO_DATE('{desde.isoformat()}', 'YYYY-MM-DD')
                          AND t.trandate <= TO_DATE('{fin.isoformat()}', 'YYYY-MM-DD')
                        GROUP BY tl.transaction""")
                    por_id = {_valor(r.get("ns_id")): r for r in dfl.to_dict("records")} if dfl is not None and len(dfl) else {}
                    # las abiertas fuera de la ventana: unidades por id
                    faltan_u = sorted({_valor(f.get("ns_id")) for f in filas
                                       if _valor(f.get("ns_id")) not in por_id and (_valor(f.get("ns_id")) or "").isdigit()})
                    for i in range(0, len(faltan_u), 200):
                        dfu = consultar_netsuite(f"""
                            SELECT tl.transaction AS ns_id, SUM(ABS(tl.quantity)) AS unidades, COUNT(*) AS lineas
                            FROM transactionline tl
                            WHERE tl.mainline = 'F' AND tl.item IS NOT NULL AND tl.transaction IN ({",".join(faltan_u[i:i + 200])})
                            GROUP BY tl.transaction""")
                        if dfu is not None and len(dfu):
                            por_id.update({_valor(r.get("ns_id")): r for r in dfu.to_dict("records")})
                    for f in filas:
                        r = por_id.get(_valor(f.get("ns_id")))
                        if r:
                            f["unidades"], f["lineas"] = r.get("unidades"), r.get("lineas")
                except Exception:
                    pass
                # OC que el WMS tiene (últimos 150 días) y no vinieron en la ventana: se traen por número
                try:
                    desde_wms = (date.today() - timedelta(days=150)).isoformat()
                    en_wms = {_num_oc(x.get("numero_oc")) for x in (supabase.table("asn_cabecera").select("numero_oc")
                              .gte("created_at", desde_wms).execute().data or []) if x.get("numero_oc")}
                    faltan = sorted(n for n in en_wms - {_num_oc(f.get("tranid")) for f in filas}
                                    if re.fullmatch(r"[A-Z0-9\-]{1,30}", n or ""))
                    for i in range(0, len(faltan), 150):
                        lote = faltan[i:i + 150]
                        lista = ",".join(f"'{n}','OC{n}'" for n in lote)
                        dfx = consultar_netsuite(self._consulta_ns(ini, fin, True, f"UPPER(TRIM(t.tranid)) IN ({lista})"))
                        if dfx is not None and len(dfx):
                            filas += dfx.where(pd.notna(dfx), None).to_dict("records")
                except Exception:
                    pass
                limpio = [{k: _valor(v) for k, v in f.items()} for f in filas]
                res = supabase.rpc("wms_oc_sincronizar", {"p_filas": limpio}).execute().data or {}
                msg_ab = ""
                if abiertas:      # si NetSuite no respondió (o vino vacío) no se cierra nada
                    ids_ab = {_valor(a.get("ns_id")) for a in abiertas}
                    try:
                        res_ab = supabase.rpc("wms_oc_sincronizar_abiertas", {
                            "p_filas": [f for f in limpio if f.get("ns_id") in ids_ab]}).execute().data or {}
                        msg_ab = f" {res_ab.get('abiertas', 0)} OC abiertas."
                    except Exception as ex_ab:
                        print(f"[CALENDARIO OC] marcar abiertas (¿falta el script 48?): {ex_ab}")
                        msg_ab = " (OC abiertas: falta ejecutar 48_oc_por_marca_contenedores.sql)"
                elif abiertas is None:
                    msg_ab = " (no se pudo leer la lista de OC abiertas en NetSuite)"
                self._meses_leidos.add((ini.year, ini.month))
                # ¿Cada OC ya tiene su recepción de artículos (Item Receipt) en NetSuite?
                msg_r = ""
                try:
                    ids = sorted({_valor(f.get("ns_id")) for f in filas if (_valor(f.get("ns_id")) or "").isdigit()})
                    marcas = self._revisar_recepciones_ns(ids)
                    if marcas:
                        supabase.rpc("wms_oc_marcar_recepcion_ns", {"p_filas": marcas}).execute()
                        msg_r = f" Recepción en NetSuite revisada en {len(marcas)} OC."
                except Exception as ex_r:
                    msg_r = f" (no se pudo revisar las recepciones en NetSuite: {str(ex_r)[:160]})"
                    print(f"[CALENDARIO OC] {ex_r}")
                msg = f"NetSuite: {res.get('leidas', 0)} OC leídas, {res.get('nuevas', 0)} nuevas.{msg_ab}{msg_r}"
            except Exception as ex:
                msg, color = f"No se pudo leer NetSuite: {getattr(ex, 'message', None) or ex}", "#B91C1C"
            finally:
                self.sincronizando = False
                self.btn_sync.disabled = False
            if not silencioso or color != "#047857":
                self._notificar(msg, color)
            self.refrescar(forzar=True)
            if callable(self.despues_de_sincronizar):
                try:
                    self.despues_de_sincronizar()
                except Exception:
                    pass
            try:
                self.page.update()
            except Exception:
                pass

        threading.Thread(target=trabajo, daemon=True).start()

    # ==================================================================
    # Pintado
    # ==================================================================
    def _filtradas(self):
        q = (self.txt_buscar.value or "").strip().upper()
        if not q:
            return list(self.filas)
        return [f for f in self.filas
                if q in str(f.get("tranid") or "").upper() or q in str(f.get("numero_oc") or "").upper()
                or q in str(f.get("proveedor") or "").upper()]

    def _pintar(self):
        filas = self._filtradas()
        ini, fin = self._rango_mes()
        campo = self.vista_fecha
        por_dia = {}
        del_mes = []
        for f in filas:
            d = _dia(f.get(campo))
            if d and ini <= d <= fin:
                por_dia.setdefault(d, []).append(f)
                del_mes.append(f)
        self._pintar_kpis(del_mes)
        self._pintar_grilla(por_dia)
        self._pintar_tabla(del_mes)
        try:
            self.page.update()
        except Exception:
            pass

    def _pintar_kpis(self, filas):
        self.k_total.value = str(len(filas))
        cerr = sum(1 for f in filas if f.get("estado") == "CERRADA")
        self.k_total_det.value = f"{cerr} cerradas · {sum(1 for f in filas if f.get('estado') == 'RECIBIENDO')} recibiendo"
        p = _promedio(f.get("dias_creacion_a_llegada") for f in filas)
        self.k_cl.value = _dias(p) if p is not None else "—"
        p2 = _promedio(f.get("dias_llegada_a_cierre") for f in filas)
        self.k_lc.value = _dias(p2) if p2 is not None else "—"
        con_esperada = [f for f in filas if f.get("llego_en") and f.get("fecha_esperada")]
        a_tiempo = sum(1 for f in con_esperada if (_n(f.get("dias_atraso")) or 0) <= 0)
        self.k_tiempo.value = f"{round(100 * a_tiempo / len(con_esperada))}%" if con_esperada else "—"
        self.k_tiempo_det.value = f"{a_tiempo} de {len(con_esperada)} llegaron hasta la fecha esperada"
        atr = [f for f in filas if f.get("estado") == "ATRASADA"]
        self.k_atr.value = str(len(atr))
        antes = sum(1 for f in filas if f.get("llego_antes_de_oc"))
        self.k_atr_det.value = f"{antes} llegaron antes de crear la OC" if antes else "pasada su fecha esperada"

    def _pintar_grilla(self, por_dia):
        hoy = date.today()
        semanas = calendar.Calendar(firstweekday=0).monthdatescalendar(self.anio, self.mes)
        filas = [ft.Row([ft.Container(expand=1, content=_t(d, 11.5, UI["texto_2"], ft.FontWeight.W_600)) for d in DIAS],
                        spacing=4)]
        for semana in semanas:
            celdas = []
            for d in semana:
                del_mes = d.month == self.mes
                lista = por_dia.get(d, [])
                citas_dia = [c for c in self.citas if str(c.get("fecha_cita") or "")[:10] == d.isoformat()]
                chips = [ft.Container(
                    padding=ft.Padding.symmetric(horizontal=6, vertical=2), border_radius=4,
                    bgcolor=ft.Colors.with_opacity(0.18, COLOR_CITA), border=ft.Border(left=ft.BorderSide(3, COLOR_CITA)),
                    content=ft.Text(f"Cita {c.get('hora_cita') or ''} {c.get('contenedor')}".replace("  ", " "), size=10.5,
                                    color=UI["texto"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    tooltip=(f"Contenedor {c.get('contenedor')} · OC {c.get('numero_oc') or '—'} · PL {c.get('referencia') or '—'}"
                             + (" · LLEGÓ" if c.get("llego_en") else "")),
                ) for c in citas_dia[:2]]
                for f in lista[:3]:
                    color, nombre = ESTADOS.get(f.get("estado"), (UI["texto_2"], ""))
                    chips.append(ft.Container(
                        padding=ft.Padding.symmetric(horizontal=6, vertical=2), border_radius=4,
                        bgcolor=ft.Colors.with_opacity(0.18, color),
                        border=ft.Border(left=ft.BorderSide(3, color)),
                        content=ft.Text(f"{f.get('tranid') or f.get('numero_oc')} · {str(f.get('proveedor') or '')[:14]}",
                                        size=10.5, color=UI["texto"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        tooltip=f"{nombre} · {f.get('proveedor') or ''}",
                        on_click=lambda e, x=f: self._detalle(x), ink=True,
                    ))
                if len(lista) > 3:
                    chips.append(ft.Text(f"+{len(lista) - 3} más", size=10.5, color=UI["acento"]))
                celdas.append(ft.Container(
                    expand=1, height=118, padding=6, border_radius=6,
                    bgcolor=UI["card_alt"] if del_mes else UI["bg"],
                    border=ft.Border.all(2 if d == hoy else 1, UI["acento"] if d == hoy else UI["borde"]),
                    on_click=(lambda e, dd=d, ll=lista: self._dialogo_dia(dd, ll)) if lista else None,
                    content=ft.Column([
                        ft.Text(str(d.day), size=12, weight=ft.FontWeight.W_700,
                                color=UI["texto"] if del_mes else UI["texto_3"]),
                        *chips,
                    ], spacing=3, tight=True),
                ))
            filas.append(ft.Row(celdas, spacing=4, vertical_alignment=ft.CrossAxisAlignment.START))
        self.grilla.controls = filas

    def _pintar_tabla(self, filas):
        rows = []
        for f in sorted(filas, key=lambda x: str(x.get(self.vista_fecha) or "")):
            color, nombre = ESTADOS.get(f.get("estado"), (UI["texto_2"], f.get("estado") or ""))
            atraso = _n(f.get("dias_atraso"))
            rows.append(ft.DataRow(
                on_select_change=lambda e, x=f: self._detalle(x),
                cells=[
                    ft.DataCell(_t(f.get("tranid") or f.get("numero_oc"), 12.5, UI["acento"], ft.FontWeight.W_700)),
                    ft.DataCell(_t(str(f.get("proveedor") or "—")[:28], 12)),
                    ft.DataCell(_chip(nombre + (" · llegó antes de la OC" if f.get("llego_antes_de_oc") else ""), color)),
                    ft.DataCell(_t(_fd(f.get("creada_en")), 11.5, UI["texto_2"])),
                    ft.DataCell(_t(_fd(f.get("fecha_esperada")), 11.5, UI["texto_2"])),
                    ft.DataCell(_t(_fd(f.get("llego_en")), 11.5, UI["texto_2"])),
                    ft.DataCell(_t(_fd(f.get("cerrada_en")), 11.5, UI["texto_2"])),
                    ft.DataCell(_t(_dias(f.get("dias_creacion_a_llegada")), 12)),
                    ft.DataCell(_t(_dias(f.get("dias_llegada_a_cierre")), 12)),
                    ft.DataCell(_t(f"{int(atraso)} d" if atraso is not None else "—", 12,
                                   UI["peligro"] if (atraso or 0) > 0 else UI["texto"])),
                ]))
        self.tabla.rows = rows
        self.txt_vacio.visible = not rows

    # ==================================================================
    # Diálogos
    # ==================================================================
    def _cerrar(self, e=None):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def _detalle(self, f):
        color, nombre = ESTADOS.get(f.get("estado"), (UI["texto_2"], f.get("estado") or ""))

        def paso(titulo, valor, nota=""):
            return ft.Row([
                ft.Container(width=10, height=10, border_radius=5, bgcolor=color if valor else UI["borde"]),
                ft.Column([_t(titulo, 12.5, peso=ft.FontWeight.W_600),
                           _t(_fd(valor) + (f"  ·  {nota}" if nota else ""), 12, UI["texto_2"])], spacing=1, tight=True),
            ], spacing=10)

        atraso = _n(f.get("dias_atraso"))
        contenido = ft.Column([
            ft.Row([_t(f.get("proveedor") or "—", 13, peso=ft.FontWeight.W_600), _chip(nombre, color)], spacing=10, wrap=True),
            _t(f"NetSuite: {f.get('estado_ns') or '—'} · {f.get('ubicacion') or f.get('bodega') or ''}", 11.5, UI["texto_3"]),
            ft.Divider(height=8, color=UI["borde"]),
            paso("Creada en NetSuite", f.get("creada_en")),
            paso("Fecha esperada", f.get("fecha_esperada"),
                 (f"llegó {int(atraso)} d tarde" if atraso and atraso > 0 and f.get("llego_en") else
                  (f"{int(atraso)} d atrasada" if atraso and atraso > 0 else ""))),
            paso("Cargada en el WMS", f.get("cargada_wms_en")),
            paso("Llegó (primer pallet)", f.get("llego_en"), _dias(f.get("dias_creacion_a_llegada")) + " desde que se creó"
                 if f.get("dias_creacion_a_llegada") is not None else ""),
            paso("Cerrada en el WMS", f.get("cerrada_en"), _dias(f.get("dias_llegada_a_cierre")) + " desde que llegó"
                 if f.get("dias_llegada_a_cierre") is not None else ""),
            ft.Divider(height=8, color=UI["borde"]),
            _t(f"Unidades OC: {int(_n(f.get('unidades_oc')) or 0):,} · recibidas: {int(_n(f.get('unidades_recibidas')) or 0):,}"
               f" · pallets: {int(_n(f.get('pallets')) or 0)}".replace(",", "."), 12),
            *([_t("La mercadería llegó antes de que existiera la OC (se recibió sin OC y se concilió después).", 12, UI["alerta"])]
              if f.get("llego_antes_de_oc") else []),
            *([_t("Esta OC está en el WMS pero no en la copia de NetSuite (presione Actualizar desde NetSuite).", 11.5, UI["texto_3"])]
              if not f.get("en_netsuite") else []),
        ], spacing=8, tight=True)
        self.page.show_dialog(ft.AlertDialog(
            bgcolor=UI["card"], title=_t(f"OC {f.get('tranid') or f.get('numero_oc')}", 18, peso=ft.FontWeight.W_700),
            content=ft.Container(width=460, content=contenido),
            actions=[ui_boton("Cerrar", None, self._cerrar, "texto")], actions_alignment=ft.MainAxisAlignment.END))

    def _dialogo_dia(self, d, lista):
        filas = []
        for f in lista:
            color, nombre = ESTADOS.get(f.get("estado"), (UI["texto_2"], ""))
            filas.append(ft.Container(
                padding=8, border_radius=6, bgcolor=UI["card_alt"], border=ft.Border(left=ft.BorderSide(3, color)),
                on_click=lambda e, x=f: (self._cerrar(), self._detalle(x)), ink=True,
                content=ft.Row([_t(f.get("tranid") or f.get("numero_oc"), 12.5, peso=ft.FontWeight.W_700),
                                _t(f.get("proveedor") or "", 12, UI["texto_2"]), _chip(nombre, color)], spacing=10, wrap=True),
            ))
        self.page.show_dialog(ft.AlertDialog(
            bgcolor=UI["card"], title=_t(f"{d.strftime('%d-%m-%Y')} · {len(lista)} OC", 18, peso=ft.FontWeight.W_700),
            content=ft.Container(width=460, height=min(420, 60 * len(lista) + 20),
                                 content=ft.Column(filas, spacing=6, scroll=ft.ScrollMode.AUTO)),
            actions=[ui_boton("Cerrar", None, self._cerrar, "texto")], actions_alignment=ft.MainAxisAlignment.END))

    # ==================================================================
    # Navegación y exportación
    # ==================================================================
    def _mover_mes(self, delta: int):
        m = self.mes + delta
        self.anio += (m - 1) // 12
        self.mes = (m - 1) % 12 + 1
        self.refrescar()

    def _ir_hoy(self):
        hoy = date.today()
        self.anio, self.mes = hoy.year, hoy.month
        self.refrescar()

    def _cambiar_vista(self):
        self.vista_fecha = self.dd_vista.value or "creada_en"
        self._pintar()

    def _exportar(self):
        ini, fin = self._rango_mes()
        filas = [f for f in self._filtradas() if (lambda d: d and ini <= d <= fin)(_dia(f.get(self.vista_fecha)))]
        if not filas:
            self._notificar("No hay OC para exportar en este mes.", "#D97706")
            return
        datos = [{
            "OC": f.get("tranid") or f.get("numero_oc"), "Proveedor": f.get("proveedor"),
            "Estado": ESTADOS.get(f.get("estado"), ("", f.get("estado")))[1], "Estado NetSuite": f.get("estado_ns"),
            "Creada en NetSuite": _fd(f.get("creada_en")), "Fecha esperada": _fd(f.get("fecha_esperada")),
            "Cargada en WMS": _fd(f.get("cargada_wms_en")), "Llegó": _fd(f.get("llego_en")),
            "Cerrada en WMS": _fd(f.get("cerrada_en")),
            "Días creada → llegó": _n(f.get("dias_creacion_a_llegada")),
            "Días llegó → cerrada": _n(f.get("dias_llegada_a_cierre")),
            "Días creada → cerrada": _n(f.get("dias_creacion_a_cierre")),
            "Días de atraso": _n(f.get("dias_atraso")),
            "Llegó antes de la OC": "Sí" if f.get("llego_antes_de_oc") else "",
            "Unidades OC": _n(f.get("unidades_oc")), "Unidades recibidas": _n(f.get("unidades_recibidas")),
            "Pallets": _n(f.get("pallets")),
        } for f in filas]
        os.makedirs("reportes_recepcion", exist_ok=True)
        ruta = os.path.join("reportes_recepcion", f"Calendario_OC_{self.anio}_{self.mes:02d}.xlsx")
        pd.DataFrame(datos).to_excel(ruta, index=False)
        descargar_o_abrir_archivo(self.page, ruta)
