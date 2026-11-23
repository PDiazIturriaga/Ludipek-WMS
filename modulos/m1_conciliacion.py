"""Recepción > Conciliar recepciones sin OC.

Cuando un contenedor llega antes de que exista la OC se recibe como "Recepción directa sin OC".
Cuando la OC se crea, aquí se eligen esos pallets (por contenedor o por día de recepción) y se asignan a la OC
seleccionada en la barra superior. Se muestra el cruce por SKU antes de confirmar, y cada
conciliación queda registrada y se puede deshacer mientras la OC no esté cerrada.
Requiere 33_conciliacion_sin_oc.sql.
"""
import threading
from datetime import datetime, timedelta

import flet as ft
from dependencias import (supabase, UI, ui_boton, ui_tarjeta, ui_tabla, ui_kpi, notificar_global,
                          obtener_bodega_activa, obtener_ahora_chile, formatear_fecha_hora_chile)

# Estados del cruce (colores de estado reservados)
EST_OK = "#0ca30c"
EST_FALTA = "#fab219"
EST_SOBRA = "#ec835a"
EST_FUERA = "#d03b3b"


def _miles(n) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except Exception:
        return str(n or 0)


def _fecha(txt: str):
    txt = (txt or "").strip().replace("/", "-")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d-%m-%y"):
        try:
            return datetime.strptime(txt, fmt).date()
        except Exception:
            pass
    return None


def _chip(texto: str, color: str, icono=None):
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        border_radius=4,
        bgcolor=ft.Colors.with_opacity(0.16, color),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.5, color)),
        content=ft.Row([
            *([ft.Icon(icono, size=13, color=color)] if icono else []),
            ft.Text(texto, size=11, weight=ft.FontWeight.W_600, color=UI["texto"]),
        ], spacing=4, tight=True),
    )


def _col(txt: str, numerica: bool = False):
    return ft.DataColumn(ft.Text(txt, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"]), numeric=numerica)


def _t(txt, peso=None, color=None, size=12):
    return ft.Text(str(txt if txt is not None else ""), size=size, weight=peso, color=color or UI["texto"])


class PanelConciliacionSinOc:
    def __init__(self, page: ft.Page, obtener_asn_id, al_conciliar=None):
        """obtener_asn_id(): id de la OC elegida en la barra superior (o None / 'LIBRES').
        al_conciliar(): se llama después de asignar o deshacer, para refrescar la vista de la OC."""
        self.page = page
        self.obtener_asn_id = obtener_asn_id
        self.al_conciliar = al_conciliar
        self.asn_id = None
        self.cabecera = {}
        self.lineas_oc = {}        # sku -> {"descripcion", "unidades"}
        self.recibido_oc = {}      # sku -> unidades ya recibidas con la OC
        self.filas = []            # registros sin OC del rango
        self.seleccion = set()     # LPN seleccionados

        hoy = obtener_ahora_chile().date()
        self.txt_desde = self._campo("Desde (DD-MM-AAAA)", (hoy - timedelta(days=30)).strftime("%d-%m-%Y"), 160)
        self.txt_hasta = self._campo("Hasta (DD-MM-AAAA)", hoy.strftime("%d-%m-%Y"), 160)
        self.txt_buscar = self._campo("Filtrar LPN, SKU o contenedor", "", 240)
        self.txt_buscar.on_change = lambda e: self._pintar()
        self.txt_desde.on_submit = lambda e: self.refrescar(forzar=True)
        self.txt_hasta.on_submit = lambda e: self.refrescar(forzar=True)
        self.chk_solo_oc = ft.Checkbox(label="Solo SKUs que vienen en la OC", value=True,
                                       label_style=ft.TextStyle(size=12, color=UI["texto"]),
                                       on_change=lambda e: self._pintar())

        self.lbl_oc = ft.Text("", size=13, weight=ft.FontWeight.W_600, color=UI["texto"])
        self.lbl_oc_det = ft.Text("", size=11.5, color=UI["texto_2"])
        self.lbl_aviso = ft.Text("", size=12, color=UI["alerta"])

        self.k_pend = ft.Text("0")
        self.k_pend_det = ft.Text("", size=11, color=UI["texto_2"])
        self.k_sel = ft.Text("0")
        self.k_sel_det = ft.Text("", size=11, color=UI["texto_2"])
        self.k_oc = ft.Text("0")
        self.k_oc_det = ft.Text("", size=11, color=UI["texto_2"])
        self.k_avance = ft.Text("0%")
        self.k_avance_det = ft.Text("", size=11, color=UI["texto_2"])

        self.fila_dias = ft.Row(spacing=8, wrap=True, run_spacing=8)
        self._lock_pintar = threading.Lock()    # la barra "En vivo" y los clics pintan desde hilos distintos
        self.agrupar = "CONTENEDOR"
        self.dd_agrupar = ft.Dropdown(
            label="Agrupar por", dense=True, width=170, value=self.agrupar,
            options=[ft.DropdownOption(key="CONTENEDOR", text="Contenedor"), ft.DropdownOption(key="DIA", text="Día")],
            bgcolor=UI["input"], border_color=UI["borde"], focused_border_color=UI["acento"],
            text_style=ft.TextStyle(size=12, color=UI["texto"]), border_radius=6,
            on_select=lambda e: self._cambiar_agrupar(),
        )
        self.lbl_grupos = ft.Text("", size=11, color=UI["texto_2"])

        self.tabla_lpn = ft.DataTable(columns=[
            _col(""), _col("Recibido"), _col("LPN"), _col("SKU"), _col("Descripción"), _col("Lote / venc."),
            _col("Cajas", True), _col("Unidades", True), _col("Contenedor"), _col("Operador"), _col("En la OC"),
        ], rows=[])
        self.tabla_cruce = ft.DataTable(columns=[
            _col("SKU"), _col("Descripción"), _col("Unid. OC", True), _col("Ya recibido con OC", True),
            _col("Sin OC seleccionado", True), _col("Total", True), _col("Diferencia", True), _col("Estado"),
        ], rows=[])
        self.tabla_hist = ft.DataTable(columns=[
            _col("Fecha"), _col("Usuario"), _col("Pallets", True), _col("Unidades", True), _col("Comentario"),
            _col("Estado"), _col(""),
        ], rows=[])

        self.btn_asignar = ui_boton("Asignar a la OC", ft.Icons.LINK_ROUNDED, self._dialogo_asignar, "primario")

        cab = ft.Row([
            ft.Column([self.lbl_oc, self.lbl_oc_det], spacing=2, tight=True, expand=True),
            ui_boton("Actualizar", ft.Icons.REFRESH_ROUNDED, lambda e: self.refrescar(forzar=True), "secundario"),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

        kpis = ft.ResponsiveRow([
            ui_kpi(self.k_pend, "Pallets sin OC en el rango", ft.Icons.INVENTORY_2_OUTLINED, UI["alerta"], self.k_pend_det),
            ui_kpi(self.k_sel, "Seleccionados", ft.Icons.CHECKLIST_ROUNDED, UI["acento"], self.k_sel_det),
            ui_kpi(self.k_oc, "Pendiente de la OC", ft.Icons.DESCRIPTION_OUTLINED, UI["primario"], self.k_oc_det),
            ui_kpi(self.k_avance, "Avance de la OC al conciliar", ft.Icons.TRENDING_UP_ROUNDED, UI["exito"], self.k_avance_det),
        ], spacing=10, run_spacing=10)

        tarjeta_lpn = ui_tarjeta(
            ft.Column([
                ft.Row([
                    self.txt_desde, self.txt_hasta,
                    ui_boton("Buscar", ft.Icons.SEARCH_ROUNDED, lambda e: self.refrescar(forzar=True), "secundario"),
                    self.txt_buscar, self.chk_solo_oc,
                ], spacing=8, wrap=True, run_spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([self.dd_agrupar, self.lbl_grupos], spacing=10,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                self.fila_dias,
                ft.Row([
                    ui_boton("Sugerir según la OC", ft.Icons.AUTO_FIX_HIGH_ROUNDED, self._sugerir, "secundario",
                             tooltip="Marca, del más antiguo al más nuevo, los pallets de SKUs de la OC hasta cubrir lo pendiente"),
                    ui_boton("Marcar visibles", ft.Icons.CHECK_BOX_OUTLINED, lambda e: self._marcar_visibles(True), "texto"),
                    ui_boton("Desmarcar todo", ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED, lambda e: self._marcar_visibles(False), "texto"),
                ], spacing=6, wrap=True, run_spacing=6),
                ui_tabla(self.tabla_lpn, 380),
            ], spacing=10, tight=True),
            titulo="1. Pallets recibidos sin OC",
            subtitulo="Marque los pallets que corresponden a la OC seleccionada arriba (un pallet se marca completo)",
            icono=ft.Icons.PALLET,
        )
        tarjeta_cruce = ui_tarjeta(
            ft.Column([ui_tabla(self.tabla_cruce, 300), self.lbl_aviso], spacing=10, tight=True),
            titulo="2. Cruce con la OC",
            subtitulo="Lo que pide la OC contra lo ya recibido con ella más lo marcado arriba",
            icono=ft.Icons.COMPARE_ARROWS_ROUNDED,
            acciones=[self.btn_asignar],
        )
        tarjeta_hist = ui_tarjeta(
            ui_tabla(self.tabla_hist, 200),
            titulo="Conciliaciones de esta OC",
            subtitulo="Se puede deshacer mientras la OC no esté cerrada; los pallets vuelven a 'sin OC'",
            icono=ft.Icons.HISTORY_ROUNDED,
        )
        self.contenido = ft.Column([kpis, tarjeta_lpn, tarjeta_cruce, tarjeta_hist], spacing=12)
        self.msg_sin_oc = ui_tarjeta(ft.Text(
            "Elija arriba, en 'Orden de compra activa', la OC que se creó para el contenedor. Aquí aparecerán los "
            "pallets recibidos sin OC para asignárselos.", size=12.5, color=UI["texto_2"]),
            titulo="Seleccione la OC", icono=ft.Icons.INFO_OUTLINE_ROUNDED)
        self.vista = ft.Column([
            ui_tarjeta(cab, titulo="Conciliar recepciones sin OC",
                       subtitulo="Asigne a una OC los pallets que se recibieron antes de que la OC existiera",
                       icono=ft.Icons.LINK_ROUNDED),
            self.msg_sin_oc,
            self.contenido,
        ], spacing=12)

    # ------------------------------------------------------------------ utilidades
    def _campo(self, label, valor, ancho):
        return ft.TextField(label=label, value=valor, width=ancho, dense=True, text_size=12,
                            color=UI["texto"], bgcolor=UI["input"], border_color=UI["borde"],
                            focused_border_color=UI["acento"], label_style=ft.TextStyle(size=11, color=UI["texto_2"]))

    def _notificar(self, txt, color="#0284C7"):
        notificar_global(self.page, txt, color)

    def _update(self):
        try:
            self.page.update()
        except Exception:
            pass

    def _usuario(self):
        return str(getattr(self.page, "usuario_actual", "") or "PC")

    @staticmethod
    def _msg_error(ex) -> str:
        msg = str(getattr(ex, "message", None) or ex)
        if ("wms_recepciones_sin_oc" in msg or "wms_conciliar" in msg or "wms_conciliaciones" in msg
                or "wms_deshacer_conciliacion" in msg) and ("not find" in msg or "does not exist" in msg):
            return "falta ejecutar 33_conciliacion_sin_oc.sql en Supabase"
        return msg.replace("WMS: ", "")

    # ------------------------------------------------------------------ carga
    def refrescar(self, forzar: bool = False):
        valor = self.obtener_asn_id()
        try:
            asn_id = int(valor) if valor not in (None, "", "LIBRES") else None
        except Exception:
            asn_id = None
        if not forzar and asn_id == self.asn_id and self.filas:
            return      # misma OC: no se pierde lo marcado (la barra "En vivo" refresca cada 8 s)
        if asn_id != self.asn_id:
            self.seleccion.clear()
        self.asn_id = asn_id
        self.msg_sin_oc.visible = asn_id is None
        self.contenido.visible = asn_id is not None
        if asn_id is None:
            self.lbl_oc.value = "Sin OC seleccionada"
            self.lbl_oc_det.value = ""
            self._update()
            return

        desde, hasta = _fecha(self.txt_desde.value), _fecha(self.txt_hasta.value)
        if not desde or not hasta:
            self._notificar("Fechas inválidas: use DD-MM-AAAA.", "#D97706")
            return
        if desde > hasta:
            desde, hasta = hasta, desde
        try:
            self.cabecera = (supabase.table("asn_cabecera").select("*").eq("id", asn_id).execute().data or [{}])[0]
            lineas = supabase.table("asn_detalle").select("sku, descripcion_proveedor, unidades_esperadas, cajas_esperadas, multiplo_empaque") \
                .eq("asn_id", asn_id).execute().data or []
            recibidos = supabase.table("registro_recepcion").select("sku, unidades_totales").eq("asn_id", asn_id).execute().data or []
            bodega = self.cabecera.get("bodega") or obtener_bodega_activa(self.page)
            self.filas = supabase.rpc("wms_recepciones_sin_oc", {
                "p_bodega": bodega, "p_desde": desde.isoformat(), "p_hasta": hasta.isoformat()}).execute().data or []
            hist = supabase.table("wms_conciliaciones_recepcion").select("*").eq("asn_id", asn_id) \
                .order("id", desc=True).execute().data or []
        except Exception as ex:
            self._notificar(f"No se pudo cargar la conciliación: {self._msg_error(ex)}", "#B91C1C")
            return

        self.lineas_oc = {}
        for l in lineas:
            s = str(l.get("sku") or "").strip().upper()
            un = int(l.get("unidades_esperadas") or 0) or int(l.get("cajas_esperadas") or 0) * int(l.get("multiplo_empaque") or 1)
            d = self.lineas_oc.setdefault(s, {"descripcion": str(l.get("descripcion_proveedor") or ""), "unidades": 0})
            d["unidades"] += un
        self.recibido_oc = {}
        for r in recibidos:
            s = str(r.get("sku") or "").strip().upper()
            self.recibido_oc[s] = self.recibido_oc.get(s, 0) + int(r.get("unidades_totales") or 0)

        lpns_vigentes = {str(f.get("lpn")) for f in self.filas}
        self.seleccion &= lpns_vigentes

        cab = self.cabecera
        oc = str(cab.get("numero_oc") or "").strip()
        oc = oc if oc and oc.upper() not in ("S/OC", "NONE") else str(cab.get("codigo_asn") or "")
        self.lbl_oc.value = f"OC {oc} · {cab.get('proveedor') or ''}"
        cont = str(cab.get("contenedor_referencia") or "").strip()
        self.lbl_oc_det.value = (f"Estado {cab.get('estado') or '-'} · {len(self.lineas_oc)} SKU · "
                                 f"{_miles(sum(v['unidades'] for v in self.lineas_oc.values()))} UN en la OC"
                                 + (f" · Contenedor {cont}" if cont else "")
                                 + f" · Rango {desde.strftime('%d-%m-%Y')} a {hasta.strftime('%d-%m-%Y')}")
        self._pintar_historial(hist)
        self._pintar()

    # ------------------------------------------------------------------ pintado
    def _visibles(self):
        q = (self.txt_buscar.value or "").strip().upper()
        solo_oc = bool(self.chk_solo_oc.value) and bool(self.lineas_oc)
        out = []
        for f in self.filas:
            sku = str(f.get("sku") or "").upper()
            if solo_oc and sku not in self.lineas_oc:
                continue
            if q and q not in f"{f.get('lpn')} {sku} {f.get('contenedor') or ''} {f.get('descripcion') or ''}".upper():
                continue
            out.append(f)
        return out

    def _toggle_lpn(self, lpn, valor):
        if valor:
            self.seleccion.add(lpn)
        else:
            self.seleccion.discard(lpn)
        self._pintar()

    @staticmethod
    def _cont(f) -> str:
        return (str(f.get("contenedor") or "").replace(" ", "").upper()) or "SIN CONTENEDOR"

    def _clave_grupo(self, f) -> str:
        return self._cont(f) if self.agrupar == "CONTENEDOR" else str(f.get("dia"))

    def _cambiar_agrupar(self):
        self.agrupar = self.dd_agrupar.value or "CONTENEDOR"
        self._pintar()

    def _toggle_dia(self, clave):
        """Marca o desmarca todos los pallets visibles del grupo (contenedor o día)."""
        lpns = {str(f["lpn"]) for f in self._visibles() if self._clave_grupo(f) == clave}
        if lpns and lpns <= self.seleccion:
            self.seleccion -= lpns
        else:
            self.seleccion |= lpns
        self._pintar()

    def _marcar_visibles(self, valor):
        lpns = {str(f["lpn"]) for f in self._visibles()}
        if valor:
            self.seleccion |= lpns
        else:
            self.seleccion.clear()
        self._pintar()

    def _sugerir(self, e=None):
        """Del más antiguo al más nuevo, marca pallets cuyos SKU estén en la OC hasta cubrir lo pendiente."""
        if not self.lineas_oc:
            self._notificar("La OC no tiene líneas cargadas; no se puede sugerir.", "#D97706")
            return
        pendiente = {s: max(v["unidades"] - self.recibido_oc.get(s, 0), 0) for s, v in self.lineas_oc.items()}
        por_lpn = {}
        for f in self.filas:
            por_lpn.setdefault(str(f["lpn"]), []).append(f)
        self.seleccion.clear()
        cont_oc = str(self.cabecera.get("contenedor_referencia") or "").strip().upper()
        orden = sorted(por_lpn.items(), key=lambda kv: (
            0 if cont_oc and any(str(x.get("contenedor") or "").upper() == cont_oc for x in kv[1]) else 1,
            min(str(x.get("dia") or "") + str(x.get("fecha_hora") or "")[11:] for x in kv[1]), kv[0]))
        for lpn, regs in orden:
            skus = {str(x.get("sku") or "").upper() for x in regs}
            if not skus <= set(self.lineas_oc):
                continue                                  # pallet con algún SKU que no viene en la OC
            if all(pendiente.get(s, 0) <= 0 for s in skus):
                continue
            self.seleccion.add(lpn)
            for x in regs:
                s = str(x.get("sku") or "").upper()
                pendiente[s] = pendiente.get(s, 0) - int(x.get("unidades") or 0)
        self._notificar(f"Se sugirieron {len(self.seleccion)} pallets. Revise el cruce antes de asignar.", "#0284C7")
        self._pintar()

    def _seleccionados(self):
        return [f for f in self.filas if str(f.get("lpn")) in self.seleccion]

    @staticmethod
    def _dia_txt(dia) -> str:
        try:
            return datetime.strptime(str(dia), "%Y-%m-%d").strftime("%d-%m-%Y")
        except Exception:
            return str(dia or "")

    def _pintar(self):
        with self._lock_pintar:
            self._pintar_interno()

    def _pintar_interno(self):
        visibles = self._visibles()
        sel = self._seleccionados()
        por_contenedor = self.agrupar == "CONTENEDOR"
        cont_oc = str(self.cabecera.get("contenedor_referencia") or "").replace(" ", "").upper()

        # Grupos: por contenedor (con sus días) o por día
        grupos = {}
        for f in visibles:
            lpn = str(f["lpn"])
            d = grupos.setdefault(self._clave_grupo(f), {"lpns": set(), "un": 0, "sel": set(), "dias": set(), "conts": set()})
            d["lpns"].add(lpn)
            d["un"] += int(f.get("unidades") or 0)
            d["dias"].add(str(f.get("dia") or ""))
            d["conts"].add(self._cont(f))
            if lpn in self.seleccion:
                d["sel"].add(lpn)

        def orden(k):
            if por_contenedor:      # el contenedor de la OC primero, "sin contenedor" al final, luego por fecha
                return (0 if k == cont_oc else 2 if k == "SIN CONTENEDOR" else 1, min(grupos[k]["dias"]), k)
            return (k,)

        chips = []
        for clave in sorted(grupos, key=orden):
            d = grupos[clave]
            completo = d["sel"] == d["lpns"]
            dias = sorted(x for x in d["dias"] if x)
            if por_contenedor:
                titulo = clave + ("  · contenedor de la OC" if cont_oc and clave == cont_oc else "")
                detalle_extra = (self._dia_txt(dias[0]) + (f" al {self._dia_txt(dias[-1])}" if len(dias) > 1 else "")) if dias else ""
            else:
                titulo = self._dia_txt(clave)
                conts = sorted(c for c in d["conts"] if c != "SIN CONTENEDOR")
                detalle_extra = ", ".join(conts[:2]) + (f" +{len(conts) - 2}" if len(conts) > 2 else "")
            es_de_oc = por_contenedor and cont_oc and clave == cont_oc
            chips.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=8), border_radius=8, ink=True,
                bgcolor=ft.Colors.with_opacity(0.18, UI["acento"]) if d["sel"] else UI["card_alt"],
                border=ft.Border.all(2 if es_de_oc else 1, UI["acento"] if (completo or es_de_oc) else UI["borde"]),
                on_click=lambda e, x=clave: self._toggle_dia(x),
                tooltip="Clic para marcar o desmarcar todos sus pallets",
                content=ft.Column([
                    ft.Text(titulo, size=12, weight=ft.FontWeight.W_700, color=UI["texto"]),
                    *([ft.Text(detalle_extra, size=10.5, color=UI["texto_3"])] if detalle_extra else []),
                    ft.Text(f"{len(d['lpns'])} pallets · {_miles(d['un'])} UN", size=11, color=UI["texto_2"]),
                    ft.Text(f"{len(d['sel'])} marcados", size=10.5,
                            color=UI["acento"] if d["sel"] else UI["texto_3"]),
                ], spacing=1, tight=True),
            ))
        if not grupos:
            chips.append(ft.Text("No hay recepciones sin OC en el rango"
                                 + (" con SKUs de esta OC." if self.chk_solo_oc.value else "."),
                                 size=12, color=UI["texto_2"]))
        self.fila_dias.controls = chips            # se reemplaza de una vez (antes se llenaba en el lugar y se duplicaba)
        self.lbl_grupos.value = ("Contenedores con pallets sin OC (clic para marcar o desmarcar todos sus pallets)"
                                 if por_contenedor else
                                 "Días con recepciones sin OC (clic para marcar o desmarcar todos sus pallets)")

        # Tabla de pallets
        filas = []
        for f in visibles[:1500]:
            lpn = str(f.get("lpn"))
            sku = str(f.get("sku") or "").upper()
            en_oc = sku in self.lineas_oc
            filas.append(ft.DataRow(cells=[
                ft.DataCell(ft.Checkbox(value=lpn in self.seleccion, on_change=lambda e, x=lpn: self._toggle_lpn(x, e.control.value))),
                ft.DataCell(_t(f.get("fecha_hora"), size=11.5)),
                ft.DataCell(_t(lpn, ft.FontWeight.W_600, UI["acento"])),
                ft.DataCell(_t(sku, ft.FontWeight.W_600)),
                ft.DataCell(_t(str(f.get("descripcion") or "")[:34], color=UI["texto_2"], size=11.5)),
                ft.DataCell(_t(f"{f.get('lote') or 'S/L'} | {f.get('vencimiento') or 'S/F'}", size=11.5)),
                ft.DataCell(_t(_miles(f.get("cajas")))),
                ft.DataCell(_t(_miles(f.get("unidades")), ft.FontWeight.W_600)),
                ft.DataCell(_t(f.get("contenedor") or "-", size=11.5, color=UI["texto_2"])),
                ft.DataCell(_t(f.get("operador") or "-", size=11.5, color=UI["texto_2"])),
                ft.DataCell(_chip("Sí", EST_OK, ft.Icons.CHECK_ROUNDED) if en_oc else _chip("No", EST_FUERA, ft.Icons.CLOSE_ROUNDED)),
            ]))
        self.tabla_lpn.rows = filas

        # Cruce por SKU
        sel_sku = {}
        for f in sel:
            s = str(f.get("sku") or "").upper()
            sel_sku[s] = sel_sku.get(s, 0) + int(f.get("unidades") or 0)
        skus = sorted(set(self.lineas_oc) | set(sel_sku), key=lambda s: (s not in sel_sku, s))
        filas_c, fuera, faltan, sobran = [], 0, 0, 0
        for s in skus:
            oc_un = self.lineas_oc.get(s, {}).get("unidades", 0)
            ya = self.recibido_oc.get(s, 0)
            nuevo = sel_sku.get(s, 0)
            total = ya + nuevo
            dif = total - oc_un
            if s not in self.lineas_oc:
                estado = _chip("No está en la OC", EST_FUERA, ft.Icons.ERROR_OUTLINE_ROUNDED)
                fuera += 1
            elif dif == 0:
                estado = _chip("Cuadra", EST_OK, ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED)
            elif dif < 0:
                estado = _chip(f"Faltan {_miles(-dif)}", EST_FALTA, ft.Icons.WARNING_AMBER_ROUNDED)
                faltan += 1
            else:
                estado = _chip(f"Sobran {_miles(dif)}", EST_SOBRA, ft.Icons.ADD_CIRCLE_OUTLINE_ROUNDED)
                sobran += 1
            desc = self.lineas_oc.get(s, {}).get("descripcion") or next(
                (str(f.get("descripcion") or "") for f in self.filas if str(f.get("sku") or "").upper() == s), "")
            filas_c.append(ft.DataRow(cells=[
                ft.DataCell(_t(s, ft.FontWeight.W_600, UI["acento"])),
                ft.DataCell(_t(desc[:34], color=UI["texto_2"], size=11.5)),
                ft.DataCell(_t(_miles(oc_un))),
                ft.DataCell(_t(_miles(ya))),
                ft.DataCell(_t(_miles(nuevo), ft.FontWeight.W_700 if nuevo else None, UI["acento"] if nuevo else UI["texto_3"])),
                ft.DataCell(_t(_miles(total), ft.FontWeight.W_600)),
                ft.DataCell(_t(("+" if dif > 0 else "") + _miles(dif))),
                ft.DataCell(estado),
            ]))
        self.tabla_cruce.rows = filas_c

        avisos = []
        if fuera:
            avisos.append(f"{fuera} SKU marcado(s) no viene(n) en la OC: quedarán como 'fuera de OC'.")
        if sobran:
            avisos.append(f"{sobran} SKU con más unidades que la OC.")
        self.lbl_aviso.value = "  ·  ".join(avisos)

        # KPIs
        lpns_rango = {str(f["lpn"]) for f in self.filas}
        self.k_pend.value = _miles(len(lpns_rango))
        self.k_pend_det.value = f"{_miles(sum(int(f.get('unidades') or 0) for f in self.filas))} UN sin OC"
        un_sel = sum(sel_sku.values())
        self.k_sel.value = f"{len(self.seleccion)} pallets"
        self.k_sel_det.value = f"{_miles(un_sel)} UN · {len(sel_sku)} SKU"
        total_oc = sum(v["unidades"] for v in self.lineas_oc.values())
        ya_oc = sum(v for s, v in self.recibido_oc.items() if s in self.lineas_oc)
        self.k_oc.value = _miles(max(total_oc - ya_oc, 0)) + " UN"
        self.k_oc_det.value = f"de {_miles(total_oc)} UN · ya recibidas {_miles(ya_oc)}"
        nuevo_oc = sum(v for s, v in sel_sku.items() if s in self.lineas_oc)
        if total_oc:
            antes = min(ya_oc / total_oc, 1) * 100
            despues = min((ya_oc + nuevo_oc) / total_oc, 1) * 100
            self.k_avance.value = f"{despues:.0f}%"
            self.k_avance_det.value = f"hoy {antes:.0f}% · {len(skus) - faltan - sobran - fuera} de {len(skus)} SKU cuadran"
        else:
            self.k_avance.value = "-"
            self.k_avance_det.value = "La OC no tiene líneas"

        self.btn_asignar.disabled = not self.seleccion
        self.btn_asignar.content = ft.Text(
            f"Asignar {len(self.seleccion)} pallets a la OC" if self.seleccion else "Asignar a la OC",
            size=12, weight=ft.FontWeight.W_600)
        self._update()

    def _pintar_historial(self, hist):
        filas = []
        for h in hist:
            deshecho = bool(h.get("deshecho_en"))
            filas.append(ft.DataRow(cells=[
                ft.DataCell(_t(formatear_fecha_hora_chile(h.get("creado_en")), size=11.5)),
                ft.DataCell(_t(h.get("usuario") or "-")),
                ft.DataCell(_t(len(h.get("lpns") or []))),
                ft.DataCell(_t(_miles(h.get("unidades")))),
                ft.DataCell(_t(h.get("comentario") or "", color=UI["texto_2"], size=11.5)),
                ft.DataCell(_chip(f"Deshecha por {h.get('deshecho_por') or '-'}", UI["texto_3"]) if deshecho
                            else _chip("Vigente", EST_OK, ft.Icons.CHECK_ROUNDED)),
                ft.DataCell(ft.Container() if deshecho else
                            ui_boton("Deshacer", ft.Icons.UNDO_ROUNDED, lambda e, x=h: self._dialogo_deshacer(x), "texto")),
            ]))
        if not filas:
            filas.append(ft.DataRow(cells=[ft.DataCell(_t("Aún no se han conciliado pallets a esta OC.", color=UI["texto_2"]))]
                                    + [ft.DataCell(_t("")) for _ in range(6)]))
        self.tabla_hist.rows = filas

    # ------------------------------------------------------------------ acciones
    def _cerrar_dialogo(self, e=None):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def _dialogo_asignar(self, e=None):
        sel = self._seleccionados()
        if not sel or self.asn_id is None:
            self._notificar("Marque al menos un pallet.", "#D97706")
            return
        un = sum(int(f.get("unidades") or 0) for f in sel)
        fuera = sorted({str(f.get("sku") or "").upper() for f in sel} - set(self.lineas_oc))
        txt_com = self._campo("Comentario (opcional)", "", 420)
        lbl_err = ft.Text("", size=12, color="#F87171")

        def confirmar(ev=None):
            try:
                r = supabase.rpc("wms_conciliar_recepciones", {
                    "p_asn_id": int(self.asn_id), "p_ids": [int(f["id"]) for f in sel],
                    "p_usuario": self._usuario(), "p_comentario": (txt_com.value or "").strip() or None,
                }).execute().data or {}
            except Exception as ex:
                lbl_err.value = f"No se asignó: {self._msg_error(ex)}"
                self._update()
                return
            self._cerrar_dialogo()
            omit = int(r.get("omitidos") or 0)
            self._notificar(f"{r.get('pallets', 0)} pallets ({_miles(r.get('unidades'))} UN) asignados a la OC {r.get('oc', '')}."
                            + (f" {omit} registros ya no estaban pendientes." if omit else ""), "#047857")
            self.seleccion.clear()
            self.refrescar(forzar=True)
            if self.al_conciliar:
                try:
                    self.al_conciliar()
                except Exception:
                    pass

        self.page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("Asignar pallets a la OC", weight=ft.FontWeight.BOLD),
            content=ft.Container(width=460, content=ft.Column([
                ft.Text(self.lbl_oc.value, size=13, weight=ft.FontWeight.W_600),
                ft.Text(f"{len(self.seleccion)} pallets · {len(sel)} líneas · {_miles(un)} UN", size=12.5),
                *([ft.Text(f"Atención: {', '.join(fuera[:6])}{'…' if len(fuera) > 6 else ''} no viene(n) en la OC y "
                           "quedará(n) como 'fuera de OC'.", size=12, color=UI["alerta"])] if fuera else []),
                ft.Text("Los pallets pasan a ser parte de la recepción de esta OC (aparecen en su conciliación, acta y "
                        "cierre). No se mueve stock. Queda registrado con su usuario y se puede deshacer mientras la "
                        "OC no esté cerrada.", size=11.5, color=UI["texto_2"]),
                txt_com, lbl_err,
            ], spacing=10, tight=True)),
            actions=[ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
                     ui_boton("Asignar", ft.Icons.LINK_ROUNDED, confirmar, "primario")],
            actions_alignment=ft.MainAxisAlignment.END,
        ))

    def _dialogo_deshacer(self, h):
        lbl_err = ft.Text("", size=12, color="#F87171")

        def confirmar(ev=None):
            try:
                r = supabase.rpc("wms_deshacer_conciliacion", {"p_id": int(h["id"]), "p_usuario": self._usuario()}).execute().data or {}
            except Exception as ex:
                lbl_err.value = f"No se deshizo: {self._msg_error(ex)}"
                self._update()
                return
            self._cerrar_dialogo()
            self._notificar(f"Conciliación deshecha: {r.get('registros', 0)} registros volvieron a 'sin OC'.", "#047857")
            self.refrescar(forzar=True)
            if self.al_conciliar:
                try:
                    self.al_conciliar()
                except Exception:
                    pass

        self.page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("Deshacer conciliación", weight=ft.FontWeight.BOLD),
            content=ft.Container(width=420, content=ft.Column([
                ft.Text(f"{len(h.get('lpns') or [])} pallets · {_miles(h.get('unidades'))} UN · "
                        f"{formatear_fecha_hora_chile(h.get('creado_en'))} · {h.get('usuario') or ''}", size=12.5),
                ft.Text("Los pallets se desligan de la OC y vuelven a 'Recepciones directas sin OC'.",
                        size=11.5, color=UI["texto_2"]),
                lbl_err,
            ], spacing=10, tight=True)),
            actions=[ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
                     ui_boton("Deshacer", ft.Icons.UNDO_ROUNDED, confirmar, "peligro")],
            actions_alignment=ft.MainAxisAlignment.END,
        ))
