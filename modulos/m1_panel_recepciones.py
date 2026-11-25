"""Recepción > Panel de recepciones.

· Lo recibido físicamente (por OC o por contenedor si fue libre) con "¿Tiene OC?" y
  "¿Cargada a NetSuite?" (se revisa solo en NetSuite si la OC ya tiene su recepción de artículos).
· Lo esperado que todavía no llega: citas de contenedores, OC/PL cargados en el WMS sin recibir
  y OC de NetSuite pendientes de recepción que el WMS aún no tiene.
· Agenda de contenedores: se pega el correo de Marco y el WMS saca contenedor, fecha, hora, OC y PL.
· Reporte de recepción: el celular finaliza la recepción y el reporte sale solo por correo a la
  lista de destinatarios (que se edita aquí). Requiere 45 y 46.
"""
import re
from datetime import date, datetime, timedelta

import flet as ft
from dependencias import (supabase, UI, ui_boton, ui_tarjeta, ui_tabla, ui_kpi, notificar_global,
                          obtener_bodega_activa, formatear_fecha_hora_chile, descargar_o_abrir_archivo)

ESTADO_NS = {
    "SI": ("#0ca30c", "Sí"),
    "PARCIAL": ("#fab219", "Parcial"),
    "NO": ("#d03b3b", "No"),
    "SIN_DATO": ("#94A3B8", "Sin dato"),
    "NO_APLICA": ("#94A3B8", "—"),
}
TIPO_ESPERADO = {
    "CITA": ("#A78BFA", "Cita contenedor"),
    "PL": ("#38BDF8", "PL cargado"),
    "OC": ("#38BDF8", "OC cargada"),
    "OC_NETSUITE": ("#64748B", "OC NetSuite"),
}

RE_CONT = re.compile(r"\b([A-Z]{4})\s?-?(\d{6,7})\b")
RE_FECHA = re.compile(r"\b(\d{1,2})[\/\-.](\d{1,2})(?:[\/\-.](\d{2,4}))?\b")
RE_HORA = re.compile(r"\b([01]?\d|2[0-3])[:.h]([0-5]\d)\s*(?:hrs?|h)?\b", re.I)
RE_OC = re.compile(r"\b(?:OC|O\.C\.?|PO|ORDEN(?:\s+DE\s+COMPRA)?)\s*[#:N°º.\-]*\s*([A-Z]{0,3}\d{3,})", re.I)
RE_PL = re.compile(r"\b(?:PL|PACKING(?:\s*LIST)?|GU[IÍ]A)\s*[#:N°º.\-]*\s*([A-Z0-9\-]{3,})", re.I)


def leer_correo_agenda(texto: str, hoy: date = None) -> list:
    """Saca las citas de un correo pegado: una fila por contenedor, con la fecha/hora de su línea
    o la última fecha que apareció antes (ej. un título 'Martes 25/11')."""
    hoy = hoy or date.today()
    filas, fecha_vigente = [], None
    for linea in (texto or "").splitlines():
        lu = linea.upper()
        f = RE_FECHA.search(lu)
        fecha_linea = None
        if f:
            d, m, a = int(f.group(1)), int(f.group(2)), f.group(3)
            anio = int(a) + (2000 if a and len(a) == 2 else 0) if a else hoy.year
            try:
                fecha_linea = date(anio, m, d)
                if not a and fecha_linea < hoy - timedelta(days=180):
                    fecha_linea = date(anio + 1, m, d)
            except ValueError:
                fecha_linea = None
        if fecha_linea:
            fecha_vigente = fecha_linea
        conts = RE_CONT.findall(lu)
        if not conts:
            continue
        h = RE_HORA.search(lu.replace(f.group(0), " ") if f else lu)
        oc = RE_OC.search(lu)
        pl = RE_PL.search(lu)
        for letras, nums in conts:
            filas.append({
                "contenedor": f"{letras}{nums}",
                "fecha_cita": (fecha_linea or fecha_vigente).isoformat() if (fecha_linea or fecha_vigente) else "",
                "hora_cita": f"{int(h.group(1)):02d}:{h.group(2)}" if h else "",
                "numero_oc": oc.group(1) if oc else "",
                "referencia": pl.group(1) if pl else "",
            })
    # un contenedor una vez por fecha
    unicas = {}
    for x in filas:
        unicas[(x["contenedor"], x["fecha_cita"])] = x
    return list(unicas.values())


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


def _campo(label, width=160, value="", **kw):
    return ft.TextField(label=label, value=value, dense=True, width=width, bgcolor=UI["input"], color=UI["texto"],
                        border_color=UI["borde"], focused_border_color=UI["acento"], border_radius=6,
                        text_style=ft.TextStyle(size=12), **kw)


def _fecha_txt(v) -> str:
    if not v:
        return "—"
    s = str(v)
    if len(s) <= 10:
        try:
            return date.fromisoformat(s[:10]).strftime("%d-%m-%Y")
        except ValueError:
            return s
    return formatear_fecha_hora_chile(v)


def _miles(v) -> str:
    try:
        return f"{int(float(v)):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


class PanelRecepciones:
    def __init__(self, page: ft.Page, sincronizar_netsuite=None):
        self.page = page
        self.sincronizar_netsuite = sincronizar_netsuite      # el del Calendario de OC
        self.datos = {"recibido": [], "esperado": []}
        self._ultima_revision_ns = None      # revisión automática de NetSuite cada 30 min al abrir el panel

        self.k_rec, self.k_rec_det = ft.Text("0"), ft.Text("últimos 30 días", size=11, color=UI["texto_3"])
        self.k_sin_oc, self.k_sin_oc_det = ft.Text("0"), ft.Text("recepciones libres", size=11, color=UI["texto_3"])
        self.k_no_ns, self.k_no_ns_det = ft.Text("0"), ft.Text("con OC, sin recepción en NetSuite", size=11, color=UI["texto_3"])
        self.k_esp, self.k_esp_det = ft.Text("0"), ft.Text("", size=11, color=UI["texto_3"])
        self.lbl_dest = ft.Text("", size=11.5, color=UI["texto_3"])

        self.tabla_rec = ft.DataTable(
            heading_row_height=38, data_row_min_height=44, data_row_max_height=56,
            columns=[_col("Recepción"), _col("Contenedor"), _col("OC / proveedor"), _col("Tiene OC"), _col("Cargada a NetSuite"),
                     _col("Pallets", True), _col("Unidades", True), _col("Recibido"), _col("Cita"), _col("Reporte")],
            rows=[])
        self.tabla_esp = ft.DataTable(
            heading_row_height=38, data_row_min_height=40, data_row_max_height=52,
            columns=[_col("Tipo"), _col("Documento"), _col("OC"), _col("Proveedor"), _col("Fecha esperada / cita"),
                     _col("Estado NetSuite"), _col("")],
            rows=[])
        self.txt_vacio_rec = _t("No hay recepciones en los últimos 30 días.", 12.5, UI["texto_2"])
        self.txt_vacio_esp = _t("No hay nada esperado pendiente.", 12.5, UI["texto_2"])

        self.vista = ft.Column([
            ft.Container(
                padding=14, border_radius=10, bgcolor=UI["card"], border=ft.Border.all(1, UI["borde"]),
                content=ft.Row([
                    ft.Column([_t("Panel de recepciones", 18, peso=ft.FontWeight.W_700),
                               _t("Lo recibido físicamente y lo que debería llegar", 12, UI["texto_2"])], spacing=2, tight=True),
                    ft.Row([
                        ui_boton("Agendar contenedores", ft.Icons.EVENT_AVAILABLE_OUTLINED, lambda e: self._dialogo_agenda(), "primario"),
                        ui_boton("Destinatarios del reporte", ft.Icons.FORWARD_TO_INBOX_OUTLINED, lambda e: self._dialogo_destinatarios(), "secundario"),
                        ui_boton("Revisar NetSuite", ft.Icons.CLOUD_SYNC_OUTLINED, lambda e: self._revisar_ns(), "secundario"),
                        ui_boton("Actualizar", ft.Icons.REFRESH_ROUNDED, lambda e: self.refrescar(), "secundario"),
                    ], spacing=8, wrap=True, run_spacing=8),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True, run_spacing=8),
            ),
            ft.ResponsiveRow([
                ui_kpi(self.k_rec, "Recepciones", ft.Icons.MOVE_TO_INBOX_ROUNDED, UI["acento"], self.k_rec_det),
                ui_kpi(self.k_sin_oc, "Sin OC", ft.Icons.LINK_OFF_ROUNDED, UI["alerta"], self.k_sin_oc_det),
                ui_kpi(self.k_no_ns, "Falta cargar en NetSuite", ft.Icons.CLOUD_OFF_OUTLINED, UI["peligro"], self.k_no_ns_det),
                ui_kpi(self.k_esp, "Esperado sin recibir", ft.Icons.SCHEDULE_ROUNDED, UI["primario"], self.k_esp_det),
            ], spacing=12, run_spacing=12),
            self.lbl_dest,
            ui_tarjeta(ft.Column([ui_tabla(self.tabla_rec, 440), self.txt_vacio_rec], spacing=8, tight=True),
                       titulo="Recibido físicamente",
                       subtitulo="«Cargada a NetSuite» se revisa sola: ¿la OC ya tiene su recepción de artículos en NetSuite?",
                       icono=ft.Icons.INVENTORY_2_OUTLINED),
            ui_tarjeta(ft.Column([ui_tabla(self.tabla_esp, 400), self.txt_vacio_esp], spacing=8, tight=True),
                       titulo="Esperado y todavía no recepcionado",
                       subtitulo="Citas de contenedores, OC/PL cargados en el WMS y OC pendientes en NetSuite",
                       icono=ft.Icons.SCHEDULE_ROUNDED),
        ], spacing=14, tight=True)

    # ==================================================================
    def _notificar(self, t, c="#0284C7"):
        notificar_global(self.page, t, c)

    def _usuario(self):
        return str(getattr(self.page, "usuario_actual", None) or "PC")

    def _bodega(self):
        return obtener_bodega_activa(self.page)

    def _cerrar(self, e=None):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def _dialogo(self, titulo, contenido, acciones, ancho=560):
        self.page.show_dialog(ft.AlertDialog(
            bgcolor=UI["card"], title=_t(titulo, 18, peso=ft.FontWeight.W_700),
            content=ft.Container(width=ancho, content=contenido), actions=acciones,
            actions_alignment=ft.MainAxisAlignment.END))

    def _error(self, ex) -> str:
        msg = str(getattr(ex, "message", None) or ex)
        if "PGRST202" in msg or "Could not find" in msg:
            return "falta ejecutar 46_panel_recepciones.sql en Supabase"
        return msg.replace("WMS: ", "", 1)

    # ==================================================================
    def refrescar(self, e=None):
        ahora = datetime.now()
        if self.sincronizar_netsuite and (self._ultima_revision_ns is None
                                          or ahora - self._ultima_revision_ns > timedelta(minutes=30)):
            self._ultima_revision_ns = ahora
            try:
                self.sincronizar_netsuite(silencioso=True)     # en segundo plano; al terminar vuelve a pintar
            except Exception:
                pass
        try:
            self.datos = supabase.rpc("wms_panel_recepciones", {"p_bodega": self._bodega(), "p_dias": 30}).execute().data or {}
        except Exception as ex:
            self.datos = {}
            self._notificar(f"No se pudo leer el panel: {self._error(ex)}", "#B91C1C")
        self._pintar()

    def refrescar_sin_revisar(self):
        """Vuelve a leer el panel sin pedir otra revisión a NetSuite (la llama el Calendario al terminar)."""
        try:
            self.datos = supabase.rpc("wms_panel_recepciones", {"p_bodega": self._bodega(), "p_dias": 30}).execute().data or {}
        except Exception:
            return
        self._pintar()

    def _pintar(self):
        rec = self.datos.get("recibido") or []
        esp = self.datos.get("esperado") or []
        self.k_rec.value = str(len(rec))
        self.k_sin_oc.value = str(sum(1 for r in rec if not r.get("tiene_oc")))
        self.k_no_ns.value = str(sum(1 for r in rec if r.get("cargada_ns") in ("NO", "PARCIAL")))
        self.k_esp.value = str(len(esp))
        self.k_esp_det.value = f"{sum(1 for x in esp if x.get('atrasado'))} atrasados"
        n_dest = int(self.datos.get("destinatarios") or 0)
        pend = int(self.datos.get("reportes_pendientes") or 0)
        self.lbl_dest.value = (f"Reporte automático de recepción: {n_dest} destinatario(s)"
                               + (f" · {pend} reporte(s) en cola" if pend else "")
                               + ("  ·  Agregue destinatarios para que se envíe." if not n_dest else ""))

        filas = []
        for r in rec:
            col_ns, txt_ns = ESTADO_NS.get(r.get("cargada_ns"), ESTADO_NS["SIN_DATO"])
            rep = r.get("reporte") or {}
            if rep.get("estado") == "ENVIADO":
                celda_rep = _t(f"Enviado {_fecha_txt(rep.get('enviado_en'))}", 11.5, UI["exito"])
            elif rep.get("estado") in ("PENDIENTE", "ENVIANDO"):
                celda_rep = _t("En cola", 11.5, UI["alerta"])
            else:
                celda_rep = ft.Row([
                    *([_t("Error", 11.5, UI["peligro"])] if rep.get("estado") == "ERROR" else []),
                    ft.TextButton("Finalizar y enviar", on_click=lambda e, x=r: self._finalizar(x),
                                  tooltip=rep.get("error") or "Pone el reporte en cola para enviarlo a los destinatarios"),
                ], spacing=4, tight=True)
            filas.append(ft.DataRow(cells=[
                ft.DataCell(_t(r.get("clave"), 11.5, UI["texto_2"])),
                ft.DataCell(_t(r.get("contenedor") or "—", 12.5, peso=ft.FontWeight.W_600)),
                ft.DataCell(_t(f"{r.get('numero_oc') or 'Sin OC'}{' · ' + str(r.get('proveedor')) if r.get('proveedor') else ''}"[:40], 12)),
                ft.DataCell(_chip("Sí" if r.get("tiene_oc") else "No", "#0ca30c" if r.get("tiene_oc") else "#fab219")),
                ft.DataCell(_chip(txt_ns + (f" ({_fecha_txt(r.get('recepcion_ns_fecha'))})" if r.get("recepcion_ns_fecha") else ""),
                                  col_ns)),
                ft.DataCell(_t(_miles(r.get("pallets")), 12.5)),
                ft.DataCell(_t(_miles(r.get("unidades")), 12.5)),
                ft.DataCell(_t(_fecha_txt(r.get("inicio")), 11.5, UI["texto_2"])),
                ft.DataCell(_t(r.get("cita") or "—", 11.5, UI["texto_2"])),
                ft.DataCell(ft.Row([celda_rep, ft.IconButton(icon=ft.Icons.TABLE_VIEW_ROUNDED, icon_size=18, icon_color=UI["acento"],
                                                             tooltip="Resumen ejecutivo en Excel",
                                                             on_click=lambda e, x=r: self._resumen_excel(x))],
                                   spacing=2, tight=True)),
            ]))
        self.tabla_rec.rows = filas
        self.txt_vacio_rec.visible = not filas

        filas_e = []
        for x in esp:
            col, nombre = TIPO_ESPERADO.get(x.get("tipo"), ("#64748B", x.get("tipo")))
            fecha = _fecha_txt(x.get("fecha")) + (f" {x.get('hora')}" if x.get("hora") else "")
            acciones = []
            if x.get("tipo") == "CITA" and x.get("id"):
                acciones.append(ft.TextButton("Cancelar cita", on_click=lambda e, i=x.get("id"): self._cancelar_cita(i)))
            filas_e.append(ft.DataRow(cells=[
                ft.DataCell(_chip(nombre, col)),
                ft.DataCell(_t(x.get("documento"), 12.5, peso=ft.FontWeight.W_600)),
                ft.DataCell(_t(x.get("numero_oc") or "—", 12)),
                ft.DataCell(_t(str(x.get("proveedor") or "—")[:30], 12)),
                ft.DataCell(_t(fecha, 12, UI["peligro"] if x.get("atrasado") else UI["texto"])),
                ft.DataCell(_t(x.get("estado_ns") or "—", 11.5, UI["texto_2"])),
                ft.DataCell(ft.Row(acciones, tight=True)),
            ]))
        self.tabla_esp.rows = filas_e
        self.txt_vacio_esp.visible = not filas_e
        try:
            self.page.update()
        except Exception:
            pass

    # ==================================================================
    def _revisar_ns(self):
        if self.sincronizar_netsuite:
            self._notificar("Revisando NetSuite (OC y sus recepciones)...", "#0284C7")
            self.sincronizar_netsuite(silencioso=False)
        else:
            self._notificar("La conexión con NetSuite no está disponible aquí.", "#D97706")

    def _finalizar(self, r):
        contenedor = (r.get("contenedor") or "").split(",")[0].strip() or None
        try:
            res = supabase.rpc("wms_recepcion_finalizar", {
                "p_bodega": self._bodega(), "p_asn_id": r.get("asn_id"), "p_contenedor": contenedor,
                "p_usuario": self._usuario()}).execute().data or {}
        except Exception as ex:
            self._notificar(f"No se pudo: {self._error(ex)}", "#B91C1C")
            return
        self._notificar(f"Reporte en cola ({res.get('pallets')} pallets). Se envía a {res.get('destinatarios')} destinatario(s).",
                        "#047857" if res.get("destinatarios") else "#B45309")
        self.refrescar()

    def _resumen_excel(self, r):
        try:
            import os
            from servicios.reporte_ejecutivo import reporte_recepcion, nombre_reporte_desde_datos
            datos = supabase.rpc("wms_reporte_recepcion", {
                "p_bodega": self._bodega(), "p_numero_oc": r.get("numero_oc") or None,
                "p_clave": None if r.get("numero_oc") else r.get("clave")}).execute().data or {}
            carpeta = os.path.join(os.getcwd(), "reportes_recepcion")
            os.makedirs(carpeta, exist_ok=True)
            if not datos.get("numero_oc") and r.get("contenedor"):
                datos = dict(datos, solo_contenedor=True, contenedor=r.get("contenedor"))   # sin OC: se identifica por contenedor
            ruta = reporte_recepcion(datos, os.path.join(carpeta, nombre_reporte_desde_datos(datos)))
            descargar_o_abrir_archivo(self.page, ruta)
        except Exception as ex:
            msg = self._error(ex)
            if "46_panel" in msg:
                msg = "falta ejecutar 51_reporte_recepcion.sql en Supabase"
            self._notificar(f"No se pudo armar el resumen: {msg}", "#B91C1C")

    def _cancelar_cita(self, id_cita):
        try:
            supabase.rpc("wms_agenda_cancelar", {"p_id": int(id_cita), "p_usuario": self._usuario()}).execute()
        except Exception as ex:
            self._notificar(f"No se pudo cancelar: {self._error(ex)}", "#B91C1C")
            return
        self.refrescar()

    # ---------------- Agenda (correo de Marco) ----------------
    def _dialogo_agenda(self):
        txt_correo = ft.TextField(
            label="Pegue aquí el correo con la agenda", multiline=True, min_lines=6, max_lines=10,
            bgcolor=UI["input"], color=UI["texto"], border_color=UI["borde"], focused_border_color=UI["acento"],
            border_radius=6, text_style=ft.TextStyle(size=12))
        lista = ft.Column(spacing=6, tight=True, scroll=ft.ScrollMode.AUTO, height=260)
        filas_ui = []

        def fila_editable(x):
            c = [_campo("Contenedor", 140, x.get("contenedor", "")), _campo("Fecha (AAAA-MM-DD)", 140, x.get("fecha_cita", "")),
                 _campo("Hora", 80, x.get("hora_cita", "")), _campo("OC", 100, x.get("numero_oc", "")),
                 _campo("PL / guía", 110, x.get("referencia", ""))]
            filas_ui.append(c)
            lista.controls.append(ft.Row(c, spacing=6, wrap=True))

        def leer(e=None):
            filas_ui.clear()
            lista.controls.clear()
            encontradas = leer_correo_agenda(txt_correo.value or "")
            for x in encontradas:
                fila_editable(x)
            if not encontradas:
                lista.controls.append(_t("No encontré números de contenedor (4 letras + 7 números). Agréguelos a mano.",
                                         12, UI["alerta"]))
            self.page.update()

        def agregar(e=None):
            fila_editable({})
            self.page.update()

        def guardar(e=None):
            datos = []
            for c in filas_ui:
                cont, fecha = (c[0].value or "").strip(), (c[1].value or "").strip()
                if not cont:
                    continue
                try:
                    if "-" in fecha and len(fecha.split("-")[0]) == 2:
                        fecha = datetime.strptime(fecha, "%d-%m-%Y").date().isoformat()
                    date.fromisoformat(fecha)
                except ValueError:
                    self._notificar(f"Fecha inválida para {cont}: use AAAA-MM-DD o DD-MM-AAAA.", "#D97706")
                    return
                datos.append({"contenedor": cont, "fecha_cita": fecha, "hora_cita": c[2].value, "numero_oc": c[3].value,
                              "referencia": c[4].value})
            if not datos:
                self._notificar("No hay citas para guardar.", "#D97706")
                return
            try:
                res = supabase.rpc("wms_agenda_guardar", {"p_filas": datos, "p_bodega": self._bodega(),
                                                          "p_usuario": self._usuario(),
                                                          "p_origen": (txt_correo.value or "")[:4000]}).execute().data or {}
            except Exception as ex:
                self._notificar(f"No se pudo guardar la agenda: {self._error(ex)}", "#B91C1C")
                return
            self._cerrar()
            self._notificar(f"{res.get('guardadas', 0)} cita(s) agendada(s).", "#047857")
            self.refrescar()

        self._dialogo("Agendar contenedores", ft.Column([
            _t("Pegue el correo de la agenda y presione «Leer correo». Revise lo que encontró antes de guardar.", 12, UI["texto_2"]),
            txt_correo,
            ft.Row([ui_boton("Leer correo", ft.Icons.AUTO_FIX_HIGH_ROUNDED, leer, "secundario"),
                    ui_boton("Agregar fila", ft.Icons.ADD_ROUNDED, agregar, "texto")], spacing=8),
            lista,
        ], spacing=10, tight=True), [ui_boton("Cancelar", None, self._cerrar, "texto"),
                                     ui_boton("Guardar agenda", ft.Icons.SAVE_ROUNDED, guardar)], ancho=720)

    # ---------------- Destinatarios del reporte ----------------
    def _dialogo_destinatarios(self):
        lista = ft.Column(spacing=4, tight=True)
        txt_correo = _campo("Correo", 260)
        txt_nombre = _campo("Nombre (opcional)", 200)
        patron = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[A-Za-z]{2,}$")

        def cargar():
            try:
                filas = supabase.table("wms_destinatarios_reportes").select("*").eq("tipo", "RECEPCION").order("correo").execute().data or []
            except Exception as ex:
                self._notificar(f"No se pudo leer la lista: {self._error(ex)}", "#B91C1C")
                filas = []
            lista.controls = [ft.Row([
                ft.Switch(value=bool(f.get("activo")), active_color=UI["exito"],
                          on_change=lambda e, i=f.get("id"): cambiar(i, e.control.value)),
                _t(f.get("correo"), 12.5, peso=ft.FontWeight.W_600), _t(f.get("nombre") or "", 12, UI["texto_2"]),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color=UI["peligro"], icon_size=18, tooltip="Quitar",
                              on_click=lambda e, i=f.get("id"): quitar(i)),
            ], spacing=8) for f in filas] or [_t("Todavía no hay destinatarios.", 12, UI["texto_2"])]
            try:
                self.page.update()
            except Exception:
                pass

        def agregar(e=None):
            correo = (txt_correo.value or "").strip().lower()
            if not patron.match(correo):
                self._notificar("Correo no válido.", "#D97706")
                return
            try:
                supabase.table("wms_destinatarios_reportes").upsert(
                    {"tipo": "RECEPCION", "correo": correo, "nombre": (txt_nombre.value or "").strip() or None, "activo": True},
                    on_conflict="tipo,correo").execute()
            except Exception as ex:
                self._notificar(f"No se pudo agregar: {self._error(ex)}", "#B91C1C")
                return
            txt_correo.value, txt_nombre.value = "", ""
            cargar()

        def cambiar(i, activo):
            try:
                supabase.table("wms_destinatarios_reportes").update({"activo": bool(activo)}).eq("id", i).execute()
            except Exception as ex:
                self._notificar(f"No se pudo cambiar: {self._error(ex)}", "#B91C1C")

        def quitar(i):
            try:
                supabase.table("wms_destinatarios_reportes").delete().eq("id", i).execute()
            except Exception as ex:
                self._notificar(f"No se pudo quitar: {self._error(ex)}", "#B91C1C")
            cargar()

        self._dialogo("Destinatarios del reporte de recepción", ft.Column([
            _t("Cuando el celular finaliza una recepción, el reporte se envía solo a los correos activos.", 12, UI["texto_2"]),
            ft.Row([txt_correo, txt_nombre, ui_boton("Agregar", ft.Icons.ADD_ROUNDED, agregar)], spacing=8, wrap=True),
            ft.Container(height=260, content=ft.Column([lista], scroll=ft.ScrollMode.AUTO)),
        ], spacing=10, tight=True), [ui_boton("Cerrar", None, lambda e: (self._cerrar(), self.refrescar()), "texto")])
        cargar()
