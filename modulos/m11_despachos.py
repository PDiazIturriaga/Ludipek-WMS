import inspect
import os
import unicodedata
from datetime import datetime

import pandas as pd
import flet as ft
from dependencias import *


# =====================================================================
# DESPACHOS DE EXPORTACIÓN (script 50) — ej. traslado Chile → Perú
# 1) Se crea el despacho y se carga el pedido desde el Excel (SKU y unidades; pallets opcional).
# 2) En el celular (Despacho exportación) o aquí se escanea cada LPN que sube: el WMS lee del stock
#    el SKU, lote, vencimiento y unidades, y calcula cajas y displays con la maestra.
# 3) Avance por SKU contra el pedido. Al cerrar se puede descontar el stock y exportar el packing list.
# =====================================================================

COLOR_ESTADO = {"ABIERTO": "#38BDF8", "CERRADO": "#10B981", "ANULADO": "#64748B"}
COLUMNAS_UNIDADES = ["units", "unidades", "aplicado (un)", "solicitado (un)", "cantidad", "un"]
COLUMNAS_PALLETS = ["pallets", "pallets a enviar", "pallet"]
COLUMNAS_DESC = ["descripcion", "descripción", "description"]


def _n(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _miles(v) -> str:
    return f"{_n(v):,}".replace(",", ".")


def _fh(v) -> str:
    return formatear_fecha_hora_chile(v) if v else "—"


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t)) if unicodedata.category(c) != "Mn").lower().strip()


def _error(ex) -> str:
    msg = getattr(ex, "message", None) or str(ex)
    if isinstance(msg, dict):
        msg = msg.get("message") or str(msg)
    msg = str(msg)
    if "PGRST202" in msg or ("wms_despacho" in msg and "Could not find" in msg):
        return "falta ejecutar 50_despachos_exportacion.sql en Supabase"
    return msg.replace("WMS: ", "", 1)


def _chip(texto: str, color: str):
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=10, vertical=4), border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.16, color), border=ft.Border.all(1, ft.Colors.with_opacity(0.5, color)),
        content=ft.Text(texto, size=11, weight=ft.FontWeight.W_600, color=UI["texto"]))


def _campo(label: str, width: int = 300, **kw):
    return ft.TextField(label=label, dense=True, width=width, bgcolor=UI["input"], color=UI["texto"],
                        border_color=UI["borde"], focused_border_color=UI["acento"], border_radius=6,
                        text_style=ft.TextStyle(size=12), **kw)


def _col(t, num=False):
    return ft.DataColumn(ft.Text(t, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"]), numeric=num)


def _t(v, size=12, color=None, peso=None):
    return ft.Text("" if v is None else str(v), size=size, color=color or UI["texto"], weight=peso)


def _empaque_txt(emp: dict) -> str:
    emp = emp or {}
    partes = [f"{_miles(emp.get('cajas'))} cj"]
    if _n(emp.get("displays")):
        partes.append(f"{_miles(emp.get('displays'))} dsp")
    if _n(emp.get("sueltas")):
        partes.append(f"{_miles(emp.get('sueltas'))} un sueltas")
    return " + ".join(partes)


def leer_pedido_excel(ruta: str) -> list:
    """Lee el pedido: SKU, descripción, unidades y pallets. Prefiere la hoja 'Envio final';
    si no, la primera hoja que tenga columna SKU y una de unidades."""
    hojas = pd.read_excel(ruta, sheet_name=None, header=None, dtype=object)
    orden = sorted(hojas.keys(), key=lambda h: (0 if "envio final" in _sin_tildes(h) else 1 if "final" in _sin_tildes(h) else 2))
    for nombre in orden:
        df = hojas[nombre]
        for i in range(min(len(df), 15)):
            cab = [_sin_tildes(x) if pd.notna(x) else "" for x in df.iloc[i].tolist()]
            if "sku" not in cab:
                continue
            c_sku = cab.index("sku")
            c_un = next((cab.index(c) for c in COLUMNAS_UNIDADES if c in cab), None)
            if c_un is None:
                continue
            c_pal = next((cab.index(c) for c in COLUMNAS_PALLETS if c in cab), None)
            c_desc = next((cab.index(c) for c in COLUMNAS_DESC if c in cab), None)
            lineas = []
            for _, fila in df.iloc[i + 1:].iterrows():
                sku = fila.iloc[c_sku]
                if pd.isna(sku) or not str(sku).strip() or _sin_tildes(sku) in ("resumen", "total"):
                    continue
                un = fila.iloc[c_un]
                try:
                    un = float(str(un).replace("\xa0", "").replace(".", "").replace(",", ".")) if isinstance(un, str) else float(un)
                except (TypeError, ValueError):
                    un = 0
                if not un or un <= 0:
                    continue
                pal = fila.iloc[c_pal] if c_pal is not None else None
                try:
                    pal = float(pal) if pal is not None and pd.notna(pal) else None
                except (TypeError, ValueError):
                    pal = None
                lineas.append({"sku": str(sku).strip().upper(),
                               "descripcion": str(fila.iloc[c_desc]).strip() if c_desc is not None and pd.notna(fila.iloc[c_desc]) else None,
                               "unidades": int(round(un)), "pallets": pal})
            if lineas:
                return lineas
    return []


class DespachosModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list):
        self.page = page
        self.despachos = []
        self.d = None              # detalle abierto (wms_despacho_detalle)
        self._subiendo = {"nombre": None}

        self.k_abiertos = ft.Text("0")
        self.k_pallets = ft.Text("0")
        self.k_unidades = ft.Text("0")
        self.k_cerrados = ft.Text("0")
        fila_kpis = ft.ResponsiveRow([
            ui_kpi(self.k_abiertos, "Despachos abiertos", ft.Icons.FLIGHT_TAKEOFF_ROUNDED, UI["acento"]),
            ui_kpi(self.k_pallets, "Pallets escaneados", ft.Icons.VIEW_IN_AR_OUTLINED, UI["primario"]),
            ui_kpi(self.k_unidades, "Unidades escaneadas", ft.Icons.INVENTORY_2_OUTLINED, UI["exito"]),
            ui_kpi(self.k_cerrados, "Cerrados (60 días)", ft.Icons.VERIFIED_ROUNDED, UI["texto_2"]),
        ], spacing=12, run_spacing=12)

        # ---------------- Lista ----------------
        self.tabla_lista = ft.DataTable(
            heading_row_height=38, data_row_min_height=44, data_row_max_height=56,
            columns=[_col("Despacho"), _col("Destino"), _col("Referencia"), _col("Contenedor"), _col("Estado"),
                     _col("Pallets", True), _col("Unidades / pedido"), _col("Creado"), _col("Cerrado"), _col("")],
            rows=[])
        self.txt_vacio = _t("No hay despachos. Cree uno con «Nuevo despacho».", 12.5, UI["texto_2"])
        self.sub_lista = ft.Column([
            ui_tarjeta(ft.Column([ui_tabla(self.tabla_lista, 420), self.txt_vacio], spacing=8, tight=True),
                       titulo="Despachos de exportación",
                       subtitulo="Presione «Abrir» para cargar el pedido (Excel), ver el avance por SKU, los LPN y el resumen Excel",
                       icono=ft.Icons.FLIGHT_TAKEOFF_ROUNDED,
                       acciones=[ui_boton("Nuevo despacho", ft.Icons.ADD_ROUNDED, lambda e: self._dialogo_nuevo())]),
        ], spacing=14, tight=True)

        # ---------------- Detalle ----------------
        self.lbl_titulo = _t("", 20, peso=ft.FontWeight.W_700)
        self.chip_estado = ft.Container()
        self.lbl_meta = _t("", 12, UI["texto_2"])
        self.barra = ft.ProgressBar(value=0, color=UI["exito"], bgcolor=UI["borde"], height=8)
        self.lbl_avance = _t("", 12.5, peso=ft.FontWeight.W_600)
        self.fila_acciones = ft.Row([], spacing=8, wrap=True)
        self.txt_scan = _campo("Escanear / escribir LPN", 260, on_submit=lambda e: self._escanear())
        self.tabla_sku = ft.DataTable(
            heading_row_height=38, data_row_min_height=44, data_row_max_height=80, column_spacing=16,
            columns=[_col("SKU"), _col("Descripción"), _col("Pedido UN", True), _col("Pallets", True), _col("Escaneado UN", True),
                     _col("Cajas · displays"), _col("Lotes y vencimientos"), _col("Peso kg", True), _col("Falta / sobra")],
            rows=[])
        self.tabla_lpn = ft.DataTable(
            heading_row_height=38, data_row_min_height=40, data_row_max_height=70, column_spacing=16,
            columns=[_col("LPN"), _col("Ubicación"), _col("Contenido (SKU · lote · venc. · empaque)"), _col("UN", True),
                     _col("Escaneado"), _col("")],
            rows=[])
        self.sub_detalle = ft.Column([
            ft.Container(
                padding=16, border_radius=10, bgcolor=UI["card"], border=ft.Border.all(1, UI["borde"]),
                content=ft.Column([
                    ft.Row([
                        ft.IconButton(icon=ft.Icons.ARROW_BACK_ROUNDED, icon_color=UI["acento"], tooltip="Volver",
                                      on_click=lambda e: self.sel_sub_despachos(0)),
                        ft.Column([ft.Row([self.lbl_titulo, self.chip_estado], spacing=12, wrap=True), self.lbl_meta],
                                  spacing=4, tight=True, expand=True),
                        self.fila_acciones,
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                    self.barra,
                    self.lbl_avance,
                ], spacing=10, tight=True)),
            ui_tarjeta(ui_tabla(self.tabla_sku, 440), titulo="Avance por SKU contra el pedido",
                       subtitulo="Cajas y displays según la maestra (UNIDAD / DISPLAY / CAJA)",
                       icono=ft.Icons.FACT_CHECK_OUTLINED),
            ui_tarjeta(ui_tabla(self.tabla_lpn, 380), titulo="LPN escaneados", icono=ft.Icons.QR_CODE_2_ROUNDED,
                       acciones=[self.txt_scan, ui_boton("Agregar LPN", ft.Icons.ADD_ROUNDED, lambda e: self._escanear(), "secundario")]),
        ], spacing=14, tight=True)

        self.contenedor = ft.Container(content=self.sub_lista)
        self.vista = ft.Container(
            padding=16, bgcolor=UI["bg"], expand=True,
            content=ft.Column([
                ui_encabezado("Despachos de exportación",
                              "Escanee los LPN que van (ej. a Perú): cajas, displays, unidades, lote y vencimiento por SKU",
                              ft.Icons.FLIGHT_TAKEOFF_ROUNDED,
                              [ui_boton("Actualizar", ft.Icons.REFRESH_ROUNDED, lambda e: self.refrescar(), "secundario")]),
                fila_kpis,
                self.contenedor,
            ], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True),
        )
        self._crear_picker()

    # ==================================================================
    def _notificar(self, texto: str, color: str = "#1E3A8A"):
        notificar_global(self.page, texto, color)

    def _usuario(self) -> str:
        return str(getattr(self.page, "usuario_actual", None) or "PC")

    def _bodega(self) -> str:
        return obtener_bodega_activa(self.page)

    def _rpc(self, nombre: str, params: dict):
        return supabase.rpc(nombre, params).execute().data

    def _update(self):
        try:
            self.page.update()
        except Exception:
            pass

    def _cerrar_dialogo(self, e=None):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def _dialogo(self, titulo: str, contenido, acciones: list, ancho: int = 460):
        self.page.show_dialog(ft.AlertDialog(
            bgcolor=UI["card"], title=_t(titulo, 18, peso=ft.FontWeight.W_700),
            content=ft.Container(width=ancho, content=contenido),
            actions=acciones, actions_alignment=ft.MainAxisAlignment.END))

    # ==================================================================
    # Lista
    # ==================================================================
    def cargar_lista(self):
        try:
            self.despachos = list(self._rpc("wms_despachos_lista", {"p_bodega": self._bodega(), "p_dias": 60}) or [])
        except Exception as ex:
            self.despachos = []
            self._notificar(f"No se pudieron leer los despachos: {_error(ex)}", "#B91C1C")
        abiertos = [d for d in self.despachos if d.get("estado") == "ABIERTO"]
        self.k_abiertos.value = str(len(abiertos))
        self.k_pallets.value = _miles(sum(_n(d.get("pallets")) for d in abiertos))
        self.k_unidades.value = _miles(sum(_n(d.get("unidades")) for d in abiertos))
        self.k_cerrados.value = str(sum(1 for d in self.despachos if d.get("estado") == "CERRADO"))
        rows = []
        for d in self.despachos:
            col = COLOR_ESTADO.get(d.get("estado"), "#64748B")
            estado = d.get("estado") + (" · stock descontado" if d.get("stock_descontado") else "")
            rows.append(ft.DataRow(
                on_select_change=lambda e, i=d.get("id"): self.abrir(i),
                cells=[
                    ft.DataCell(ft.TextButton(d.get("numero"), on_click=lambda e, i=d.get("id"): self.abrir(i),
                                              tooltip="Abrir: cargar pedido, ver avance y exportar")),
                    ft.DataCell(_t(d.get("destino"), 12)),
                    ft.DataCell(_t(str(d.get("referencia") or "—")[:40], 12)),
                    ft.DataCell(_t(d.get("contenedor") or "—", 12)),
                    ft.DataCell(_chip(estado, col)),
                    ft.DataCell(_t(_miles(d.get("pallets")), 12)),
                    ft.DataCell(_t(f"{_miles(d.get('unidades'))} / {_miles(d.get('pedido_unidades'))}", 12)),
                    ft.DataCell(_t(f"{_fh(d.get('creado_en'))} · {d.get('creado_por') or ''}", 11.5, UI["texto_2"])),
                    ft.DataCell(_t(_fh(d.get("cerrado_en")) if d.get("cerrado_en") else "—", 11.5, UI["texto_2"])),
                    ft.DataCell(ui_boton("Abrir" + (" y cargar pedido" if d.get("estado") == "ABIERTO" and not _n(d.get("skus_pedido")) else ""),
                                         ft.Icons.OPEN_IN_FULL_ROUNDED, lambda e, i=d.get("id"): self.abrir(i), "secundario")),
                ]))
        self.tabla_lista.rows = rows
        self.txt_vacio.visible = not rows

    def _dialogo_nuevo(self):
        txt_dest = _campo("Destino", 200, value="PERÚ")
        txt_ref = _campo("Referencia / pedido", 380, hint_text="Ej: Traslado Feral nov-2026")
        txt_cont = _campo("Contenedor (opcional)", 220)

        def crear(e=None):
            try:
                d = self._rpc("wms_despacho_crear", {"p_bodega": self._bodega(), "p_destino": txt_dest.value,
                                                     "p_referencia": txt_ref.value, "p_contenedor": txt_cont.value,
                                                     "p_usuario": self._usuario()})
            except Exception as ex:
                self._notificar(f"No se pudo crear: {_error(ex)}", "#B91C1C")
                return
            self._cerrar_dialogo()
            self.d = d
            self._mostrar_detalle()
            self._notificar("Despacho creado. Cargue el pedido (Excel) y escanee los LPN.", "#047857")

        self._dialogo("Nuevo despacho de exportación", ft.Column([txt_dest, txt_ref, txt_cont], spacing=10, tight=True),
                      [ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"), ui_boton("Crear", ft.Icons.CHECK_ROUNDED, crear)])

    # ==================================================================
    # Detalle
    # ==================================================================
    def abrir(self, despacho_id):
        try:
            self.d = self._rpc("wms_despacho_detalle", {"p_id": int(despacho_id)}) or {}
        except Exception as ex:
            self._notificar(f"No se pudo abrir el despacho: {_error(ex)}", "#B91C1C")
            return
        self._mostrar_detalle()

    def _mostrar_detalle(self):
        self._pintar_detalle()
        self.contenedor.content = self.sub_detalle
        self._update()

    def _pintar_detalle(self):
        d = self.d or {}
        cab = d.get("despacho") or {}
        tot = d.get("totales") or {}
        abierto = cab.get("estado") == "ABIERTO"
        self.lbl_titulo.value = f"{cab.get('numero')} · {cab.get('destino')}"
        self.chip_estado.content = _chip(str(cab.get("estado")) + (" · stock descontado" if cab.get("stock_descontado") else ""),
                                         COLOR_ESTADO.get(cab.get("estado"), "#64748B"))
        self.lbl_meta.value = (f"{cab.get('referencia') or 'Sin referencia'} · contenedor {cab.get('contenedor') or '—'} · "
                               f"creado {_fh(cab.get('creado_en'))} por {cab.get('creado_por') or ''}"
                               + (f" · cerrado {_fh(cab.get('cerrado_en'))} por {cab.get('cerrado_por')}" if cab.get("cerrado_en") else ""))
        ped = _n(tot.get("pedido_unidades"))
        un = _n(tot.get("unidades"))
        self.barra.value = min(1.0, un / ped) if ped else (1.0 if un else 0)
        self.lbl_avance.value = (f"{_miles(tot.get('pallets'))} pallets · {_miles(tot.get('cajas'))} cajas · "
                                 f"{_miles(tot.get('displays'))} displays · {_miles(un)} UN"
                                 + (f" de {_miles(ped)} pedidas ({un * 100 // ped}%)" if ped else " (sin pedido cargado)")
                                 + (f" · pallets pedidos {float(tot.get('pedido_pallets')):g}" if tot.get("pedido_pallets") else "")
                                 + " · peso neto aprox. " + f"{float(tot.get('peso_kg') or 0):,.0f}".replace(",", ".") + " kg")

        acciones = [ui_boton("Resumen Excel", ft.Icons.TABLE_VIEW_ROUNDED, lambda e: self._exportar(), "secundario",
                             tooltip="Resumen ejecutivo: por pallet, por vencimiento y por SKU contra el pedido")]
        if abierto:
            acciones = [ui_boton("Cargar pedido (Excel)", ft.Icons.UPLOAD_FILE_ROUNDED, self._elegir_excel, "secundario"),
                        ui_boton("Editar datos", ft.Icons.EDIT_ROUNDED, lambda e: self._dialogo_editar(), "secundario")] + acciones + [
                        ui_boton("Cerrar despacho", ft.Icons.VERIFIED_ROUNDED, lambda e: self._dialogo_cerrar()),
                        ui_boton("Anular", ft.Icons.BLOCK_ROUNDED, lambda e: self._dialogo_anular(), "peligro")]
        elif cab.get("estado") == "CERRADO" and not cab.get("stock_descontado"):
            acciones += [ui_boton("Descontar stock", ft.Icons.REMOVE_SHOPPING_CART_OUTLINED, lambda e: self._dialogo_descontar(), "peligro"),
                         ui_boton("Reabrir", ft.Icons.LOCK_OPEN_ROUNDED, lambda e: self._accion("wms_despacho_reabrir", {}, "Despacho reabierto."), "secundario")]
        self.fila_acciones.controls = acciones
        self.txt_scan.disabled = not abierto

        rows = []
        for s in d.get("sku") or []:
            pedido = s.get("pedido_unidades")
            falta, sobra = _n(s.get("falta")), _n(s.get("sobra"))
            if not _n(tot.get("pedido_unidades")):
                est, col = "Sin pedido cargado", UI["texto_2"]
            elif not s.get("en_pedido"):
                est, col = "Fuera del pedido", UI["alerta"]
            elif falta:
                est, col = f"Faltan {_miles(falta)}", UI["peligro"] if not _n(s.get("unidades")) else UI["alerta"]
            elif sobra:
                est, col = f"Sobran {_miles(sobra)}", UI["alerta"]
            else:
                est, col = "Completo", UI["exito"]
            lotes = "\n".join(f"{l.get('lote')} · {l.get('vencimiento')} · {_miles(l.get('unidades'))} UN ({_empaque_txt(l.get('empaque'))})"
                              for l in (s.get("lotes") or [])[:4]) or "—"
            rows.append(ft.DataRow(cells=[
                ft.DataCell(_t(s.get("sku"), 12.5, peso=ft.FontWeight.W_700)),
                ft.DataCell(_t(str(s.get("descripcion") or "")[:34], 11.5, UI["texto_2"])),
                ft.DataCell(_t(_miles(pedido) if pedido is not None else "—", 12)),
                ft.DataCell(_t(f"{_n(s.get('pallets'))}" + (f" / {float(s.get('pedido_pallets')):g}" if s.get("pedido_pallets") else ""), 12)),
                ft.DataCell(_t(_miles(s.get("unidades")), 12.5, peso=ft.FontWeight.W_600)),
                ft.DataCell(_t(_empaque_txt(s.get("empaque")) + f"  (caja x{s.get('multiplo_caja')}"
                               + (f", display x{s.get('multiplo_display')}" if 1 < _n(s.get("multiplo_display")) < _n(s.get("multiplo_caja")) else "") + ")", 11.5)),
                ft.DataCell(_t(lotes, 11, UI["texto_2"])),
                ft.DataCell(_t(f"{float(s.get('peso_kg') or 0):,.0f}".replace(",", "."), 12)),
                ft.DataCell(_t(est, 12, col, ft.FontWeight.W_600)),
            ]))
        self.tabla_sku.rows = rows

        rows_l = []
        for l in d.get("lpns") or []:
            cont = "\n".join(f"{c.get('sku')} · {c.get('lote')} · {c.get('vencimiento')} · {_empaque_txt(c.get('empaque'))}"
                             for c in (l.get("contenido") or [])[:4])
            rows_l.append(ft.DataRow(cells=[
                ft.DataCell(_t(l.get("lpn"), 12.5, UI["acento"], ft.FontWeight.W_700)),
                ft.DataCell(_t(l.get("ubicacion") or "—", 12)),
                ft.DataCell(_t(cont, 11.5)),
                ft.DataCell(_t(_miles(l.get("unidades")), 12)),
                ft.DataCell(_t(f"{_fh(l.get('escaneado_en'))} · {l.get('escaneado_por') or ''}", 11, UI["texto_2"])),
                ft.DataCell(ft.IconButton(icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color=UI["peligro"], icon_size=18,
                                          tooltip="Quitar del despacho", disabled=not abierto,
                                          on_click=lambda e, x=l.get("lpn"): self._quitar(x))),
            ]))
        self.tabla_lpn.rows = rows_l

    def _id(self):
        return int(((self.d or {}).get("despacho") or {}).get("id"))

    def _accion(self, funcion: str, params: dict, ok: str = None):
        try:
            res = self._rpc(funcion, {"p_id": self._id(), **params, "p_usuario": self._usuario()})
        except Exception as ex:
            self._notificar(f"No se pudo: {_error(ex)}", "#B91C1C")
            return None
        if isinstance(res, dict) and "despacho" in res:
            self.d = res
        elif isinstance(res, dict) and res.get("detalle"):
            self.d = res["detalle"]
        self._pintar_detalle()
        self._update()
        if ok:
            self._notificar(ok, "#047857")
        return res

    def _escanear(self):
        lpn = (self.txt_scan.value or "").strip()
        if not lpn:
            return
        res = self._accion("wms_despacho_escanear", {"p_lpn": lpn})
        self.txt_scan.value = ""
        if res:
            if res.get("resultado") == "YA_ESTABA":
                self._notificar(f"{res.get('lpn')} ya estaba en el despacho.", "#D97706")
            else:
                avisos = res.get("avisos") or []
                self._notificar(f"{res.get('lpn')} agregado ({res.get('ubicacion')})." + (" Ojo: " + "; ".join(avisos) if avisos else ""),
                                "#B45309" if avisos else "#047857")
        try:
            self.txt_scan.focus()
        except Exception:
            pass
        self._update()

    def _quitar(self, lpn):
        self._accion("wms_despacho_quitar_lpn", {"p_lpn": lpn}, f"{lpn} quitado del despacho.")

    def _dialogo_editar(self):
        cab = (self.d or {}).get("despacho") or {}
        txt_dest = _campo("Destino", 200, value=cab.get("destino") or "")
        txt_ref = _campo("Referencia / pedido", 380, value=cab.get("referencia") or "")
        txt_cont = _campo("Contenedor", 220, value=cab.get("contenedor") or "")
        txt_nota = _campo("Nota", 380, value=cab.get("nota") or "", multiline=True, min_lines=2)

        def guardar(e=None):
            self._cerrar_dialogo()
            self._accion("wms_despacho_editar", {"p_destino": txt_dest.value, "p_referencia": txt_ref.value,
                                                 "p_contenedor": txt_cont.value, "p_nota": txt_nota.value}, "Datos guardados.")

        self._dialogo("Datos del despacho", ft.Column([txt_dest, txt_ref, txt_cont, txt_nota], spacing=10, tight=True),
                      [ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"), ui_boton("Guardar", ft.Icons.SAVE_ROUNDED, guardar)])

    def _dialogo_cerrar(self):
        tot = (self.d or {}).get("totales") or {}
        chk = ft.Checkbox(label="Descontar del stock los LPN escaneados (salen de su ubicación)", value=True)
        faltan = [s for s in (self.d or {}).get("sku") or [] if _n(s.get("falta"))]

        def confirmar(e=None):
            self._cerrar_dialogo()
            res = self._accion("wms_despacho_cerrar", {"p_descontar": bool(chk.value)})
            if res:
                self._notificar(f"Despacho {res.get('numero')} cerrado"
                                + (f": {res.get('lpn_descontados')} LPN y {_miles(res.get('unidades_descontadas'))} UN descontados del stock."
                                   if chk.value else " sin descontar stock."), "#047857")

        self._dialogo("Cerrar despacho", ft.Column([
            _t(f"{_miles(tot.get('pallets'))} pallets · {_miles(tot.get('unidades'))} UN escaneadas.", 13, peso=ft.FontWeight.W_600),
            *([_t("Faltan unidades de: " + ", ".join(f"{s.get('sku')} ({_miles(s.get('falta'))})" for s in faltan[:8]), 12, UI["alerta"])]
              if faltan else []),
            chk,
            _t("El descuento queda en el kardex como DESPACHO_EXPORTACION, con copia de cada fila en el despacho.", 11.5, UI["texto_3"]),
        ], spacing=10, tight=True), [ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
                                     ui_boton("Cerrar despacho", ft.Icons.VERIFIED_ROUNDED, confirmar)], ancho=520)

    def _dialogo_descontar(self):
        def confirmar(e=None):
            self._cerrar_dialogo()
            res = self._accion("wms_despacho_descontar", {})
            if res:
                self._notificar(f"{res.get('lpn_descontados')} LPN y {_miles(res.get('unidades_descontadas'))} UN descontados del stock.", "#047857")

        self._dialogo("Descontar stock", _t("Los LPN del despacho salen de sus ubicaciones. ¿Continuar?", 12.5),
                      [ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
                       ui_boton("Descontar", ft.Icons.REMOVE_SHOPPING_CART_OUTLINED, confirmar, "peligro")])

    def _dialogo_anular(self):
        def confirmar(e=None):
            self._cerrar_dialogo()
            self._accion("wms_despacho_anular", {}, "Despacho anulado.")

        self._dialogo("Anular despacho", _t("El despacho queda anulado y sus LPN se pueden usar en otro. El stock no cambia.", 12.5),
                      [ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
                       ui_boton("Anular", ft.Icons.BLOCK_ROUNDED, confirmar, "peligro")])

    # ==================================================================
    # Pedido desde Excel
    # ==================================================================
    def _crear_picker(self):
        params = inspect.signature(ft.FilePicker.__init__).parameters
        kw = {}
        if "on_result" in params:
            kw["on_result"] = self._al_elegir
        if "on_upload" in params:
            kw["on_upload"] = self._al_subir
        self.picker = ft.FilePicker(**kw)
        try:
            if self.picker not in self.page.services:
                self.page.services.append(self.picker)
        except Exception:
            try:
                self.page.overlay.append(self.picker)
            except Exception:
                pass

    async def _elegir_excel(self, e=None):
        try:
            kw = {"allow_multiple": False, "allowed_extensions": ["xlsx", "xls"]}
            if "with_data" in inspect.signature(self.picker.pick_files).parameters:
                kw["with_data"] = True
            res = self.picker.pick_files(**kw)
            if inspect.isawaitable(res):
                res = await res
                if res is not None:
                    from types import SimpleNamespace
                    await self._al_elegir(SimpleNamespace(files=getattr(res, "files", res)))
        except Exception as ex:
            self._notificar(f"No se pudo abrir el selector de archivos: {ex}", "#B91C1C")

    async def _al_elegir(self, e):
        archivos = getattr(e, "files", None)
        if not archivos:
            return
        f = archivos[0]
        ruta = getattr(f, "path", None)
        if ruta and os.path.isfile(ruta):
            self._procesar_pedido(ruta)
            return
        nombre = os.path.basename(str(getattr(f, "name", "pedido.xlsx")))
        self._subiendo["nombre"] = nombre
        datos = getattr(f, "bytes", None)
        if datos:
            destino = os.path.join(os.getcwd(), "assets", "uploads", nombre)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(destino, "wb") as fh:
                fh.write(bytes(datos))
            self._procesar_pedido(destino)
            return
        try:
            url = self.page.get_upload_url(nombre, 600)
            r = self.picker.upload([ft.FilePickerUploadFile(upload_url=url, name=nombre)])
            if inspect.isawaitable(r):
                await r
            self._notificar(f"Subiendo {nombre}...", "#0284C7")
        except Exception as ex:
            self._notificar(f"Error subiendo el Excel: {ex}", "#B91C1C")

    async def _al_subir(self, e):
        if getattr(e, "error", None):
            self._notificar(f"Error durante la subida: {e.error}", "#B91C1C")
            return
        if float(getattr(e, "progress", 0) or 0) < 1:
            return
        nombre = os.path.basename(str(self._subiendo.get("nombre") or getattr(e, "file_name", "") or ""))
        for carpeta in (os.path.join(os.getcwd(), "assets", "uploads"), os.path.join(os.getcwd(), "uploads"),
                        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "uploads")):
            ruta = os.path.join(carpeta, nombre)
            if nombre and os.path.isfile(ruta):
                self._procesar_pedido(ruta)
                return
        self._notificar("El Excel subió pero no se encontró en el servidor. Intente de nuevo.", "#B91C1C")

    def _procesar_pedido(self, ruta: str):
        try:
            lineas = leer_pedido_excel(ruta)
        except Exception as ex:
            self._notificar(f"No se pudo leer el Excel: {ex}", "#B91C1C")
            return
        if not lineas:
            self._notificar("No encontré el pedido en el Excel: se necesita una hoja con columna SKU y una de unidades "
                            "(Units, Unidades o Aplicado).", "#B91C1C")
            return
        total = sum(l["unidades"] for l in lineas)
        pallets = sum(l["pallets"] or 0 for l in lineas)
        tabla = ft.DataTable(
            heading_row_height=34, data_row_min_height=30, data_row_max_height=36,
            columns=[_col("SKU"), _col("Descripción"), _col("Unidades", True), _col("Pallets", True)],
            rows=[ft.DataRow(cells=[ft.DataCell(_t(l["sku"], 12)), ft.DataCell(_t(str(l["descripcion"] or "")[:36], 11.5, UI["texto_2"])),
                                    ft.DataCell(_t(_miles(l["unidades"]), 12)),
                                    ft.DataCell(_t(f"{l['pallets']:g}" if l["pallets"] else "—", 12))]) for l in lineas])

        def confirmar(e=None):
            self._cerrar_dialogo()
            self._accion("wms_despacho_pedido_cargar", {"p_lineas": lineas}, f"Pedido cargado: {len(lineas)} SKU.")

        self._dialogo("Pedido leído del Excel", ft.Column([
            _t(f"{len(lineas)} SKU · {_miles(total)} unidades" + (f" · {pallets:g} pallets" if pallets else ""), 13, peso=ft.FontWeight.W_600),
            ft.Container(height=320, content=ft.Column([tabla], scroll=ft.ScrollMode.AUTO)),
            _t("Reemplaza el pedido que tenía el despacho. Los LPN escaneados no cambian.", 11.5, UI["texto_3"]),
        ], spacing=8, tight=True), [ui_boton("Cancelar", None, self._cerrar_dialogo, "texto"),
                                    ui_boton("Cargar pedido", ft.Icons.CHECK_ROUNDED, confirmar)], ancho=640)

    # ==================================================================
    # Packing list
    # ==================================================================
    def _exportar(self):
        d = self.d or {}
        cab = d.get("despacho") or {}
        if not (d.get("lpns") or d.get("sku")):
            self._notificar("El despacho está vacío.", "#D97706")
            return
        try:
            from servicios.reporte_ejecutivo import reporte_despacho
            os.makedirs("reportes_despachos", exist_ok=True)
            ruta = reporte_despacho(d, os.path.join("reportes_despachos",
                                                    f"Resumen_Despacho_{cab.get('numero')}_{datetime.now():%Y%m%d_%H%M}.xlsx"))
            descargar_o_abrir_archivo(self.page, ruta)
        except Exception as ex:
            self._notificar(f"No se pudo armar el resumen: {ex}", "#B91C1C")

    # ==================================================================
    # Navegación
    # ==================================================================
    def sel_sub_despachos(self, idx: int = 0):
        self.cargar_lista()
        self.contenedor.content = self.sub_lista
        self._update()

    def refrescar(self, e=None):
        if self.contenedor.content is self.sub_detalle and self.d:
            self.abrir(self._id())
        else:
            self.sel_sub_despachos(0)
