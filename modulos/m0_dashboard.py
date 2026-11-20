"""Tablero operativo (m0).

Todos los datos son reales: vienen de una sola función de Supabase (wms_dashboard_resumen,
script 29). Antes había valores fijos o estimados (horas dock-to-stock inventadas, UPH acotado,
porcentajes calculados a ojo).

Gráficos construidos con controles Flet (sin librerías externas), siguiendo reglas de
visualización profesional:
  · marcas delgadas con extremo redondeado de 4 px apoyadas en la línea base
  · grilla y ejes discretos (hairline), una sola escala por gráfico
  · paleta categórica validada para daltonismo sobre el fondo oscuro de la app
    (Recepción azul · Almacenamiento verde agua · Despacho naranjo), en orden fijo
  · leyenda siempre que hay 2+ series; textos en tinta neutra, nunca en el color de la serie
  · colores de estado (bueno/advertencia/serio/crítico) reservados y siempre con ícono + texto
  · tooltip al pasar el mouse con los valores exactos
"""
from datetime import datetime

import flet as ft

from dependencias import *

# ---------------------------------------------------------------------
# Tokens visuales (superficie oscuro de la app)
# ---------------------------------------------------------------------
SUPERFICIE = UI["card"]
INK = UI["texto"]
INK_2 = UI["texto_2"]
INK_3 = UI["texto_3"]
GRILLA = "#2E393C"
BASE = "#3B484B"

SERIES = [  # orden fijo, validado (CVD ΔE ≥ 9.4, normal ≥ 20.9, contraste ≥ 3:1 sobre #232B2D)
    ("recepcion", "Recepción", "#3987e5"),
    ("almacenamiento", "Almacenamiento", "#199e70"),
    ("despacho", "Despacho (picking)", "#d95926"),
]
MAGNITUD = "#3987e5"   # una sola tonalidad para magnitudes (ocupación, embudo)
ESTADO = {"bueno": "#0ca30c", "advertencia": "#fab219", "serio": "#ec835a", "critico": "#d03b3b"}
DIAS = {1: "lun", 2: "mar", 3: "mié", 4: "jue", 5: "vie", 6: "sáb", 7: "dom"}


def _miles(n) -> str:
    try:
        return f"{int(round(float(n))):,}".replace(",", ".")
    except Exception:
        return "0"


def _compacto(n) -> str:
    n = float(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".", ",").replace(",0M", "M")
    if n >= 10_000:
        return f"{n / 1000:.0f}K"
    return _miles(n)


def _tope_limpio(v: float) -> float:
    """Máximo de escala redondeado (1, 2, 2.5, 5 × 10^n)."""
    if v <= 0:
        return 1
    import math
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp


def _radio_arriba(r=4):
    return ft.BorderRadius(top_left=r, top_right=r, bottom_left=0, bottom_right=0)


def _radio_derecha(r=4):
    return ft.BorderRadius(top_left=0, top_right=r, bottom_left=0, bottom_right=r)


def _muestra(color: str):
    return ft.Container(width=10, height=10, border_radius=2, bgcolor=color)


def _leyenda(items: list):
    return ft.Row([ft.Row([_muestra(c), ft.Text(t, size=11, color=INK_2)], spacing=6, tight=True) for t, c in items],
                  spacing=16, wrap=True)


def _tarjeta(titulo: str, subtitulo: str, contenido, col=None, accion=None):
    return ft.Container(
        col=col, padding=16, bgcolor=SUPERFICIE, border_radius=10, border=ft.Border.all(1, UI["borde"]),
        content=ft.Column([
            ft.Row([
                ft.Column([ft.Text(titulo, size=14, weight=ft.FontWeight.W_600, color=INK),
                           ft.Text(subtitulo, size=11, color=INK_2)], spacing=2, tight=True, expand=True),
                *([accion] if accion else []),
            ], vertical_alignment=ft.CrossAxisAlignment.START),
            contenido,
        ], spacing=14, tight=True),
    )


def _vacio(texto: str):
    return ft.Container(height=120, alignment=ft.Alignment.CENTER,
                        content=ft.Text(texto, size=12, color=INK_3, text_align=ft.TextAlign.CENTER))


# ---------------------------------------------------------------------
# Gráfico de columnas agrupadas (unidades por día)
# ---------------------------------------------------------------------
def grafico_columnas_dia(dias: list, alto: int = 190):
    if not dias or not any(d.get(k, 0) for d in dias for k, _, _ in SERIES):
        return _vacio("Sin movimientos registrados en el período.")
    tope = _tope_limpio(max(max(d.get(k, 0) for k, _, _ in SERIES) for d in dias))
    n = len(dias)
    ancho_barra = 8 if n <= 14 else 5

    eje_y = ft.Column(
        [ft.Text(_compacto(tope * f), size=10, color=INK_3, text_align=ft.TextAlign.RIGHT, width=40)
         for f in (1, 0.75, 0.5, 0.25, 0)],
        height=alto + 8, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, horizontal_alignment=ft.CrossAxisAlignment.END,
    )
    grilla = ft.Column(
        [ft.Container(expand=True, border=ft.Border(top=ft.BorderSide(1, GRILLA))) for _ in range(4)]
        + [ft.Container(height=0, border=ft.Border(top=ft.BorderSide(1, BASE)))],
        spacing=0, height=alto, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    grupos = []
    for d in dias:
        etiqueta_dia = f"{DIAS.get(d.get('dow'), '')} {d.get('dia')}"
        barras = []
        for clave, nombre, color in SERIES:
            v = float(d.get(clave, 0) or 0)
            h = 0 if v <= 0 else max(2, v / tope * alto)
            barras.append(ft.Container(width=ancho_barra, height=h, bgcolor=color, border_radius=_radio_arriba(3)))
        detalle = "\n".join(f"{nombre}: {_miles(d.get(clave, 0))} UN" for clave, nombre, _ in SERIES)
        grupos.append(ft.Container(
            expand=True, height=alto, tooltip=f"{etiqueta_dia}\n{detalle}",
            content=ft.Row(barras, spacing=2, alignment=ft.MainAxisAlignment.CENTER,
                           vertical_alignment=ft.CrossAxisAlignment.END),
        ))
    eje_x = ft.Row(
        [ft.Text(d.get("dia", "")[:2] if (i % 2 == 0 or n <= 10 or i == n - 1) else "", size=10,
                 color=INK_3 if d.get("dow") in (6, 7) else INK_2, text_align=ft.TextAlign.CENTER, expand=True)
         for i, d in enumerate(dias)],
        spacing=0,
    )
    totales = {k: sum(float(d.get(k, 0) or 0) for d in dias) for k, _, _ in SERIES}
    return ft.Column([
        _leyenda([(f"{nom} · {_compacto(totales[k])} UN", c) for k, nom, c in SERIES]),
        ft.Row([
            eje_y,
            ft.Column([ft.Stack([grilla, ft.Row(grupos, spacing=0, height=alto)], height=alto), eje_x],
                      spacing=4, expand=True),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
    ], spacing=12)


# ---------------------------------------------------------------------
# Barras horizontales (una serie) y apiladas
# ---------------------------------------------------------------------
def barra_h(etiqueta: str, valor: float, tope: float, texto_valor: str, color: str = MAGNITUD,
            tooltip: str = None, sufijo=None, ancho_etiqueta: int = 132):
    frac = 0 if tope <= 0 else max(0.0, min(1.0, valor / tope))
    largo = int(frac * 1000)
    return ft.Container(
        tooltip=tooltip or f"{etiqueta}: {texto_valor}",
        content=ft.Row([
            ft.Text(etiqueta, size=12, color=INK_2, width=ancho_etiqueta, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Container(expand=True, height=12, content=ft.Row([
                *([ft.Container(expand=largo, height=12, bgcolor=color, border_radius=_radio_derecha(4))] if largo > 0 else []),
                *([ft.Container(expand=1000 - largo)] if largo < 1000 else []),
            ], spacing=0)),
            ft.Text(texto_valor, size=12, weight=ft.FontWeight.W_600, color=INK, width=78, text_align=ft.TextAlign.RIGHT),
            *([sufijo] if sufijo else []),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def barra_apilada_h(etiqueta: str, partes: list, tope: float, texto_valor: str, ancho_etiqueta: int = 132):
    """partes = [(nombre, valor, color)]; 2 px de separación entre segmentos."""
    total = sum(max(0, v) for _, v, _ in partes)
    frac = 0 if tope <= 0 else min(1.0, total / tope)
    segmentos = [p for p in partes if p[1] > 0]
    detalle = "\n".join(f"{n}: {_miles(v)} UN" for n, v, _ in partes)
    filas = []
    for i, (n, v, c) in enumerate(segmentos):
        filas.append(ft.Container(expand=max(1, int(v / max(1, total) * 1000)), height=12, bgcolor=c,
                                  border_radius=_radio_derecha(4) if i == len(segmentos) - 1 else 0))
    largo = int(frac * 1000)
    return ft.Container(
        tooltip=f"{etiqueta}\n{detalle}",
        content=ft.Row([
            ft.Text(etiqueta, size=12, color=INK_2, width=ancho_etiqueta, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Container(expand=True, height=12, content=ft.Row([
                *([ft.Container(expand=largo, content=ft.Row(filas, spacing=2))] if largo > 0 and filas else []),
                *([ft.Container(expand=1000 - largo)] if largo < 1000 else []),
            ], spacing=0)),
            ft.Text(texto_valor, size=12, weight=ft.FontWeight.W_600, color=INK, width=78, text_align=ft.TextAlign.RIGHT),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def chip_estado(nivel: str, texto: str):
    icono = {"bueno": ft.Icons.CHECK_CIRCLE_ROUNDED, "advertencia": ft.Icons.WARNING_AMBER_ROUNDED,
             "serio": ft.Icons.ERROR_OUTLINE_ROUNDED, "critico": ft.Icons.REPORT_ROUNDED}[nivel]
    return ft.Row([ft.Icon(icono, size=14, color=ESTADO[nivel]), ft.Text(texto, size=11, color=INK_2)],
                  spacing=4, tight=True, width=96)


class DashboardModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list, navegar_callback):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables
        self.navegar_callback = navegar_callback
        self.datos = None
        self.sub_actual = 0
        self.ultimo_id_recepcion = None

        self.lbl_actualizado = ft.Text("", size=11, color=INK_3)
        self.contenedor = ft.Container()
        cabecera = ft.Row([
            ft.Column([
                ft.Text("Tablero operativo", size=18, weight=ft.FontWeight.W_700, color=INK),
                self.lbl_actualizado,
            ], spacing=2, expand=True),
            ui_boton("Actualizar", ft.Icons.SYNC_ROUNDED, lambda e: self.refrescar_dashboard(), "secundario"),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

        self.vista = ft.Container(
            padding=16, bgcolor=UI["bg"], expand=True,
            content=ft.Column([cabecera, self.contenedor], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True),
        )
        # Compatibilidad con main.py
        self.subvista_360 = self.subvista_labor = self.subvista_salud = self.contenedor
        self.contenedor.content = _vacio("Cargando datos del tablero…")

    # ------------------------------------------------------------------
    def refrescar_dashboard(self, e=None):
        bodega = obtener_bodega_activa(self.page)
        try:
            self.datos = supabase.rpc("wms_dashboard_resumen", {"p_bodega": bodega, "p_dias": 14}).execute().data or {}
        except Exception as ex:
            msg = str(getattr(ex, "message", None) or ex)
            if "wms_dashboard_resumen" in msg and ("not find" in msg or "does not exist" in msg):
                msg = "Falta ejecutar 29_dashboard.sql en Supabase."
            self.contenedor.content = _vacio(f"No se pudieron cargar los datos del tablero.\n{msg}")
            self.page.update()
            return
        self.lbl_actualizado.value = f"{self.datos.get('bodega', bodega)} · actualizado {self.datos.get('generado', '')}"
        self._aviso_recepcion_nueva(bodega)
        self.contenedor.content = self._construir(self.sub_actual)
        self.page.update()

    def sel_sub_dash(self, idx: int):
        self.sub_actual = idx if idx in (0, 1, 2) else 0
        if self.datos is None:
            self.refrescar_dashboard()
            return
        self.contenedor.content = self._construir(self.sub_actual)
        self.page.update()

    def _aviso_recepcion_nueva(self, bodega: str):
        """Aviso emergente cuando entra un pallet nuevo en recepción (se mantiene del tablero anterior)."""
        try:
            r = (supabase.table("registro_recepcion").select("id, lpn, sku, unidades_totales, lote").eq("bodega", bodega)
                 .order("id", desc=True).limit(1).execute().data or [])
            if not r:
                return
            top = r[0]
            if self.ultimo_id_recepcion is not None and top.get("id") != self.ultimo_id_recepcion:
                lote, qa = extraer_estado_qa(top.get("lote", "S/L"))
                mostrar_aviso_ingreso_modal_global(self.page, str(top.get("lpn")), str(top.get("sku")),
                                                   str(top.get("unidades_totales", 0)), lote, qa)
            self.ultimo_id_recepcion = top.get("id")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Piezas
    # ------------------------------------------------------------------
    def _tiles(self):
        k = self.datos.get("kpis", {})
        tot, ocu = int(k.get("posiciones_total") or 0), int(k.get("posiciones_ocupadas") or 0)
        pct = (ocu / tot * 100) if tot else 0

        def det(t):
            return ft.Text(t, size=11, color=INK_3)

        col = {"xs": 12, "sm": 6, "md": 4, "xl": 2}
        return ft.ResponsiveRow([
            ui_kpi(ft.Text(_miles(k.get("ov_picking"))), "Órdenes por pickear", ft.Icons.SHOPPING_CART_OUTLINED, SERIES[2][2],
                   det(f"{_miles(k.get('ov_picking_farmacia'))} farmacia · {_miles(k.get('ov_sin_asignar'))} sin asignar"), col=col),
            ui_kpi(ft.Text(_miles(k.get("ov_packing"))), "En packing", ft.Icons.INVENTORY_ROUNDED, SERIES[2][2],
                   det(f"{_miles(k.get('ov_por_facturar'))} por facturar"), col=col),
            ui_kpi(ft.Text(_miles(k.get("cerradas_hoy"))), "Órdenes cerradas hoy", ft.Icons.TASK_ALT_ROUNDED, ESTADO["bueno"],
                   det(f"{_miles(k.get('ov_en_transito'))} traslados en tránsito"), col=col),
            ui_kpi(ft.Text(_miles(k.get("anden"))), "Pallets en andén", ft.Icons.MOVE_TO_INBOX_ROUNDED, SERIES[0][2],
                   det("pendientes de ubicar"), col=col),
            ui_kpi(ft.Text(f"{pct:.0f}%"), "Ocupación de racks", ft.Icons.GRID_VIEW_ROUNDED,
                   ESTADO["critico"] if pct > 85 else (ESTADO["advertencia"] if pct > 80 else SERIES[1][2]),
                   det(f"{_miles(ocu)} de {_miles(tot)} posiciones"), col=col),
            ui_kpi(ft.Text(_compacto(k.get("unidades_stock"))), "Unidades en stock", ft.Icons.WAREHOUSE_OUTLINED, SERIES[1][2],
                   det(f"{_miles(k.get('skus_stock'))} SKU distintos"), col=col),
        ], spacing=12, run_spacing=12)

    def _card_movimientos(self, col):
        return _tarjeta("Unidades movidas por día", "Últimos 14 días · recepción, almacenamiento y despacho (picking)",
                        grafico_columnas_dia(self.datos.get("movimientos_dia") or []), col=col)

    def _card_embudo(self, col):
        k = self.datos.get("kpis", {})
        etapas = [("Por pickear", k.get("ov_picking", 0)), ("En packing", k.get("ov_packing", 0)),
                  ("Por facturar", k.get("ov_por_facturar", 0)), ("En tránsito CCP", k.get("ov_en_transito", 0)),
                  ("Cerradas hoy", k.get("cerradas_hoy", 0))]
        tope = _tope_limpio(max([int(v or 0) for _, v in etapas] + [1]))
        filas = [barra_h(n, int(v or 0), tope, _miles(v), MAGNITUD, ancho_etiqueta=110) for n, v in etapas]
        return _tarjeta("Flujo de órdenes", "Cuántas órdenes hay en cada etapa ahora",
                        ft.Column(filas, spacing=12), col=col)

    def _card_operadores(self, col):
        ops = self.datos.get("operadores_hoy") or []
        if not ops:
            cont = _vacio("Todavía no hay movimientos de operadores hoy.")
        else:
            tope = _tope_limpio(max(float(o.get("unidades") or 0) for o in ops))
            filas = [barra_apilada_h(
                str(o.get("usuario") or ""),
                [(SERIES[0][1], float(o.get("recepcion") or 0), SERIES[0][2]),
                 (SERIES[1][1], float(o.get("almacenamiento") or 0), SERIES[1][2]),
                 (SERIES[2][1], float(o.get("despacho") or 0), SERIES[2][2])],
                tope, f"{_compacto(o.get('unidades'))} UN") for o in ops]
            cont = ft.Column([_leyenda([(n, c) for _, n, c in SERIES]), ft.Column(filas, spacing=10)], spacing=14)
        return _tarjeta("Productividad de hoy por operador", "Unidades procesadas en el día, por tipo de tarea (top 10)",
                        cont, col=col)

    def _card_ocupacion(self, col):
        grupos = self.datos.get("ocupacion") or []
        filas = []
        for g in grupos:
            tot, ocu = int(g.get("total") or 0), int(g.get("ocupadas") or 0)
            if tot <= 0:
                continue
            pct = ocu / tot * 100
            nivel = "critico" if pct > 85 else ("advertencia" if pct > 80 else None)
            filas.append(barra_h(g.get("grupo", ""), pct, 100, f"{pct:.0f}%", MAGNITUD,
                                 tooltip=f"{g.get('grupo')}: {ocu} de {tot} posiciones con stock ({pct:.1f}%)",
                                 sufijo=chip_estado(nivel, "Saturado" if nivel == "critico" else "Alta")
                                 if nivel else ft.Container(width=96), ancho_etiqueta=96))
        cont = ft.Column(filas, spacing=10) if filas else _vacio("Sin maestra de ubicaciones.")
        return _tarjeta("Ocupación por rack y zona", "Posiciones con stock sobre el total habilitado · alerta sobre 80 %",
                        cont, col=col)

    def _card_vencimientos(self, col):
        tramos = self.datos.get("vencimientos") or []
        nivel_por_orden = {1: "critico", 2: "serio", 3: "advertencia"}
        tope = _tope_limpio(max([float(t.get("unidades") or 0) for t in tramos] + [1]))
        filas = []
        for t in tramos:
            orden = int(t.get("orden") or 0)
            un = float(t.get("unidades") or 0)
            nivel = nivel_por_orden.get(orden)
            filas.append(barra_h(
                t.get("tramo", ""), un, tope, _compacto(un),
                ESTADO[nivel] if nivel else (INK_3 if orden == 6 else MAGNITUD),
                tooltip=f"{t.get('tramo')}: {_miles(un)} UN en {t.get('lotes')} lote(s)",
                sufijo=chip_estado(nivel, {"critico": "Vencido", "serio": "Urgente", "advertencia": "Atención"}[nivel])
                if nivel and un > 0 else ft.Container(width=96), ancho_etiqueta=118))
        return _tarjeta("Stock por vencimiento", "Unidades disponibles según cuánto falta para que venzan",
                        ft.Column(filas, spacing=10), col=col)

    def _card_alertas(self, col):
        alertas = self.datos.get("alertas") or []
        nivel = {"ALTA": "critico", "MEDIA": "advertencia", "BAJA": "bueno"}
        filas = []
        for a in alertas[:8]:
            nv = nivel.get(a.get("severidad"), "advertencia")
            icono = {"critico": ft.Icons.REPORT_ROUNDED, "advertencia": ft.Icons.WARNING_AMBER_ROUNDED,
                     "bueno": ft.Icons.INFO_OUTLINE_ROUNDED}[nv]
            filas.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=10, vertical=8), border_radius=8, bgcolor=UI["card_alt"],
                content=ft.Row([
                    ft.Icon(icono, size=18, color=ESTADO[nv] if nv != "bueno" else INK_2),
                    ft.Text(a.get("titulo", ""), size=12, color=INK, expand=True, max_lines=2),
                    ft.Text(_miles(a.get("cantidad")), size=13, weight=ft.FontWeight.W_700, color=INK),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))
        cont = ft.Column(filas, spacing=6) if filas else _vacio("Sin alertas: todo en orden.")
        return _tarjeta("Requiere atención", f"{len(alertas)} alerta(s) activas · detalle en el portal de inicio", cont, col=col)

    def _card_oc(self, col):
        ocs = self.datos.get("oc_abiertas") or []
        if not ocs:
            return _tarjeta("Recepciones abiertas", "Órdenes de compra en recepción", _vacio("No hay recepciones abiertas."), col=col)
        tabla = ft.DataTable(
            heading_row_height=34, data_row_min_height=36, data_row_max_height=40, column_spacing=18,
            heading_row_color=UI["card_alt"], divider_thickness=0.5,
            columns=[ft.DataColumn(ft.Text(c, size=11, weight=ft.FontWeight.W_600, color=INK_2),
                                   numeric=c in ("PALLETS", "UNIDADES"))
                     for c in ("OC / RECEPCIÓN", "PROVEEDOR", "PALLETS", "UNIDADES", "ESTADO")],
            rows=[ft.DataRow(cells=[
                ft.DataCell(ft.Text(formatear_nombre_po(o.get("codigo") or ""), size=12, weight=ft.FontWeight.W_600, color=INK)),
                ft.DataCell(ft.Text(str(o.get("proveedor") or "")[:28], size=12, color=INK_2)),
                ft.DataCell(ft.Text(f"{_miles(o.get('lpns'))}" + (f" de {o.get('pallets_esperados')}" if o.get("pallets_esperados") else ""),
                                    size=12, color=INK)),
                ft.DataCell(ft.Text(_miles(o.get("unidades")), size=12, color=INK)),
                ft.DataCell(ft.Text(str(o.get("estado") or "EN RECEPCIÓN").upper(), size=11, color=INK_2)),
            ]) for o in ocs],
        )
        return _tarjeta("Recepciones abiertas", "Órdenes de compra con pallets en recepción",
                        ft.Row([tabla], scroll=ft.ScrollMode.AUTO), col=col)

    # ------------------------------------------------------------------
    def _construir(self, idx: int):
        if not self.datos:
            return _vacio("Sin datos.")
        if idx == 1:      # Flujo y productividad
            cuerpo = [
                ft.ResponsiveRow([self._card_movimientos({"xs": 12})], spacing=12, run_spacing=12),
                ft.ResponsiveRow([self._card_operadores({"xs": 12, "lg": 7}), self._card_embudo({"xs": 12, "lg": 5})],
                                 spacing=12, run_spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            ]
        elif idx == 2:    # Inventario
            cuerpo = [
                ft.ResponsiveRow([self._card_ocupacion({"xs": 12, "lg": 6}), self._card_vencimientos({"xs": 12, "lg": 6})],
                                 spacing=12, run_spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                ft.ResponsiveRow([self._card_oc({"xs": 12})], spacing=12, run_spacing=12),
            ]
        else:             # Resumen
            cuerpo = [
                ft.ResponsiveRow([self._card_movimientos({"xs": 12, "lg": 8}), self._card_alertas({"xs": 12, "lg": 4})],
                                 spacing=12, run_spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                ft.ResponsiveRow([self._card_embudo({"xs": 12, "lg": 4}), self._card_ocupacion({"xs": 12, "lg": 4}),
                                  self._card_vencimientos({"xs": 12, "lg": 4})],
                                 spacing=12, run_spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                ft.ResponsiveRow([self._card_oc({"xs": 12})], spacing=12, run_spacing=12),
            ]
        return ft.Column([self._tiles(), *cuerpo], spacing=12)
