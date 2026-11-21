"""Mov. Stock > Consolidar picking (script 38).

Stock que está en una ubicación de picking (nivel 01 o ZONA-PICKING) que NO es la asignada a su
SKU (wms_ubicacion_picking_sku). Se puede mover a su ubicación de picking actual con un clic; cada
movimiento queda en el kardex como CONSOLIDACION_PICKING. Filtro por marca (ej. INABA), SKU o
descripción.
"""
import flet as ft

from dependencias import (supabase, UI, ui_boton, ui_tarjeta, ui_tabla, ui_kpi, notificar_global,
                          obtener_bodega_activa)


def _miles(n) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except Exception:
        return str(n or 0)


def _t(txt, peso=None, color=None, size=12):
    return ft.Text(str(txt if txt is not None else ""), size=size, weight=peso, color=color or UI["texto"])


def _col(txt, numerica=False):
    return ft.DataColumn(ft.Text(txt, size=11.5, weight=ft.FontWeight.W_600, color=UI["texto_2"]), numeric=numerica)


class PanelConsolidarPicking:
    def __init__(self, page: ft.Page):
        self.page = page
        self.filas = []
        self.seleccion = set()
        self.txt_filtro = ft.TextField(label="Marca, SKU o descripción (vacío = todo)", value="INABA", width=300,
                                       dense=True, text_size=12, color=UI["texto"], bgcolor=UI["input"],
                                       border_color=UI["borde"], focused_border_color=UI["acento"],
                                       label_style=ft.TextStyle(size=11, color=UI["texto_2"]),
                                       on_submit=lambda e: self.refrescar())
        self.k_filas = ft.Text("0")
        self.k_skus = ft.Text("0")
        self.k_un = ft.Text("0")
        self.k_sel = ft.Text("0")
        self.tabla = ft.DataTable(columns=[
            _col(""), _col("SKU"), _col("Descripción"), _col("Marca"), _col("Está en"), _col("Debe ir a"),
            _col("Lote / venc."), _col("Unidades", True), _col("LPN"),
        ], rows=[])
        self.btn_mover = ui_boton("Mover a su ubicación de picking", ft.Icons.MOVE_DOWN_ROUNDED, self._confirmar, "primario")
        self.vista = ft.Column([
            ft.ResponsiveRow([
                ui_kpi(self.k_filas, "Filas fuera de lugar", ft.Icons.WRONG_LOCATION_OUTLINED, UI["alerta"]),
                ui_kpi(self.k_skus, "SKU afectados", ft.Icons.INVENTORY_2_OUTLINED, UI["primario"]),
                ui_kpi(self.k_un, "Unidades", ft.Icons.NUMBERS_ROUNDED, UI["acento"]),
                ui_kpi(self.k_sel, "Seleccionadas", ft.Icons.CHECKLIST_ROUNDED, UI["exito"]),
            ], spacing=10, run_spacing=10),
            ui_tarjeta(ft.Column([
                ft.Row([self.txt_filtro,
                        ui_boton("Buscar", ft.Icons.SEARCH_ROUNDED, lambda e: self.refrescar(), "secundario"),
                        ui_boton("Marcar todo", ft.Icons.CHECK_BOX_OUTLINED, lambda e: self._marcar(True), "texto"),
                        ui_boton("Desmarcar", ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED, lambda e: self._marcar(False), "texto"),
                        self.btn_mover], spacing=8, wrap=True, run_spacing=8,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Text("Stock que quedó en una ubicación de picking distinta a la que hoy tiene asignada su SKU "
                        "(por ejemplo, después de reasignar el picking de INABA). Moverlo deja todo el picking del "
                        "SKU en un solo lugar y el picking lo encuentra al tiro. Queda en el kardex.",
                        size=11.5, color=UI["texto_2"]),
                ui_tabla(self.tabla, 520),
            ], spacing=10, tight=True), titulo="Picking fuera de su ubicación",
                subtitulo="Ubicación asignada: Admin › Maestra (picking fijo) o carga del script 19",
                icono=ft.Icons.MOVE_DOWN_ROUNDED),
        ], spacing=12)

    def _update(self):
        try:
            self.page.update()
        except Exception:
            pass

    @staticmethod
    def _msg(ex) -> str:
        m = str(getattr(ex, "message", None) or ex)
        if ("wms_picking_fuera_de_lugar" in m or "wms_consolidar_picking" in m) and ("not find" in m or "does not exist" in m):
            return "falta ejecutar 38_ot_picking_pallets_fotos.sql en Supabase"
        return m.replace("WMS: ", "")

    def refrescar(self, e=None):
        try:
            self.filas = supabase.rpc("wms_picking_fuera_de_lugar", {
                "p_bodega": obtener_bodega_activa(self.page), "p_filtro": (self.txt_filtro.value or "").strip() or None,
            }).execute().data or []
        except Exception as ex:
            notificar_global(self.page, f"No se pudo cargar: {self._msg(ex)}", "#B45309")
            self.filas = []
        ids = {int(f["id"]) for f in self.filas}
        self.seleccion &= ids
        self._pintar()

    def _marcar(self, valor):
        self.seleccion = {int(f["id"]) for f in self.filas} if valor else set()
        self._pintar()

    def _toggle(self, fid, valor):
        (self.seleccion.add if valor else self.seleccion.discard)(fid)
        self._pintar()

    def _pintar(self):
        self.tabla.rows = [ft.DataRow(cells=[
            ft.DataCell(ft.Checkbox(value=int(f["id"]) in self.seleccion,
                                    on_change=lambda e, x=int(f["id"]): self._toggle(x, e.control.value))),
            ft.DataCell(_t(f.get("sku"), ft.FontWeight.W_600, UI["acento"])),
            ft.DataCell(_t(str(f.get("descripcion") or "")[:34], color=UI["texto_2"], size=11.5)),
            ft.DataCell(_t(f.get("marca") or "-", color=UI["texto_2"], size=11.5)),
            ft.DataCell(_t(f.get("ubicacion_actual"), ft.FontWeight.W_600, UI["alerta"])),
            ft.DataCell(_t(f.get("ubicacion_asignada"), ft.FontWeight.W_600, UI["exito"])),
            ft.DataCell(_t(f"{f.get('lote') or 'S/L'} | {f.get('fecha_vencimiento_cl') or 'S/F'}", size=11.5)),
            ft.DataCell(_t(_miles(f.get("unidades")), ft.FontWeight.W_600)),
            ft.DataCell(_t(f.get("lpn") or "-", color=UI["texto_2"], size=11.5)),
        ]) for f in self.filas[:2000]]
        self.k_filas.value = _miles(len(self.filas))
        self.k_skus.value = _miles(len({f.get("sku") for f in self.filas}))
        self.k_un.value = _miles(sum(int(f.get("unidades") or 0) for f in self.filas))
        self.k_sel.value = _miles(len(self.seleccion))
        self.btn_mover.disabled = not self.seleccion
        self._update()

    def _confirmar(self, e=None):
        if not self.seleccion:
            return
        sel = [f for f in self.filas if int(f["id"]) in self.seleccion]
        un = sum(int(f.get("unidades") or 0) for f in sel)

        def cerrar(ev=None):
            try:
                self.page.pop_dialog()
            except Exception:
                pass

        def mover(ev=None):
            cerrar()
            try:
                r = supabase.rpc("wms_consolidar_picking", {
                    "p_bodega": obtener_bodega_activa(self.page), "p_ids": sorted(self.seleccion),
                    "p_usuario": str(getattr(self.page, "usuario_actual", "") or "PC"),
                }).execute().data or {}
            except Exception as ex:
                notificar_global(self.page, f"No se movió: {self._msg(ex)}", "#B91C1C")
                return
            notificar_global(self.page, f"{r.get('movidas', 0)} filas ({_miles(r.get('unidades'))} UN) movidas a su "
                                        "ubicación de picking.", "#047857")
            self.seleccion.clear()
            self.refrescar()

        self.page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("Mover a su ubicación de picking", weight=ft.FontWeight.BOLD),
            content=ft.Container(width=440, content=ft.Text(
                f"{len(sel)} filas · {len({f.get('sku') for f in sel})} SKU · {_miles(un)} UN.\n\n"
                "Mueva físicamente las cajas a la ubicación indicada en 'Debe ir a'. El sistema las cambia de "
                "ubicación y lo registra en el kardex (CONSOLIDACION_PICKING).", size=12.5)),
            actions=[ui_boton("Cancelar", None, cerrar, "texto"),
                     ui_boton("Mover", ft.Icons.MOVE_DOWN_ROUNDED, mover, "primario")],
            actions_alignment=ft.MainAxisAlignment.END))
