import json
from datetime import datetime
import flet as ft
from dependencias import *


class RecepcionTrasladosCcpModulo:
    """Recepción profesional de traslados Santiago -> Concepción por OT y LPN."""

    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables
        self.ot_activa = None
        self.pallets_esperados = {}
        self.lpns_recibidos = set()

        BG = "#1B2122"; CARD = "#262E30"; INPUT = "#1D2426"; BORDER = "#3B484B"
        WHITE = "#F8FAFC"; MUTED = "#94A3B8"; CYAN = "#38BDF8"; TEAL = "#0F766E"

        self.txt_buscar = ft.TextField(
            label="Buscar OT-CCP / cliente", dense=True, width=300, bgcolor=INPUT,
            color=WHITE, border_color=BORDER, focused_border_color=CYAN,
            prefix_icon=ft.Icons.SEARCH_ROUNDED, on_submit=lambda e: self.cargar_bandeja(),
        )
        self.txt_scan_lpn = ft.TextField(
            label="Escanear LPN recibido", dense=True, expand=True, bgcolor=INPUT,
            color=WHITE, border_color=BORDER, focused_border_color="#34D399",
            prefix_icon=ft.Icons.QR_CODE_SCANNER_ROUNDED,
            on_submit=lambda e: self.procesar_lpn(),
        )
        self.lbl_ot = ft.Text("SIN OT ACTIVA", size=16, weight=ft.FontWeight.W_900, color=WHITE)
        self.lbl_meta = ft.Text("Seleccione un traslado pendiente", size=10.5, color=MUTED)
        self.lbl_kpi_ot = ft.Text("0", size=20, weight=ft.FontWeight.W_900, color=CYAN)
        self.lbl_kpi_lpn = ft.Text("0 / 0", size=20, weight=ft.FontWeight.W_900, color="#34D399")
        self.lbl_kpi_un = ft.Text("0", size=20, weight=ft.FontWeight.W_900, color="#FBBF24")
        self.lbl_kpi_pct = ft.Text("0%", size=20, weight=ft.FontWeight.W_900, color="#A78BFA")

        self.tabla_ots = ft.DataTable(
            heading_row_color="#181E20", heading_row_height=36, data_row_min_height=42,
            data_row_max_height=48, column_spacing=14, horizontal_margin=9,
            data_text_style=ft.TextStyle(color=WHITE, size=10.5),
            columns=[
                ft.DataColumn(ft.Text("OT TRASLADO", color=CYAN, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("DESTINO", color=WHITE, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("LPN", color="#34D399", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("UNIDADES", color="#FBBF24", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("ESTADO", color=WHITE, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("ACCIÓN", color=CYAN, weight=ft.FontWeight.BOLD)),
            ], rows=[])
        self.tabla_lpns = ft.DataTable(
            heading_row_color="#181E20", heading_row_height=36, data_row_min_height=40,
            data_row_max_height=46, column_spacing=12, horizontal_margin=8,
            data_text_style=ft.TextStyle(color=WHITE, size=10.5),
            columns=[
                ft.DataColumn(ft.Text("LPN", color=CYAN, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("SKU", color=WHITE, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("CAJAS", color="#34D399", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("DISPLAY", color=WHITE, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("UNIDADES", color="#FBBF24", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("ESTADO", color=WHITE, weight=ft.FontWeight.BOLD)),
            ], rows=[])

        self.cont_ots = envolver_tabla_scroll(self.tabla_ots, 330)
        self.cont_lpns = envolver_tabla_scroll(self.tabla_lpns, 360)

        def kpi(titulo, valor, color, icono):
            return ft.Container(
                col={"xs": 12, "sm": 6, "md": 3, "lg": 3}, padding=12,
                bgcolor="#121718", border_radius=8, border=ft.Border.all(1, color),
                content=ft.Row([ft.Icon(icono, color=color, size=24),
                    ft.Column([valor, ft.Text(titulo, size=10, color=MUTED, weight=ft.FontWeight.BOLD)], spacing=1)], spacing=9))

        self.sub_bandeja = ft.Column([
            ft.ResponsiveRow([
                kpi("OT EN TRÁNSITO", self.lbl_kpi_ot, CYAN, ft.Icons.LOCAL_SHIPPING_OUTLINED),
                kpi("LPN RECIBIDOS", self.lbl_kpi_lpn, "#34D399", ft.Icons.QR_CODE_2_ROUNDED),
                kpi("UNIDADES ESPERADAS", self.lbl_kpi_un, "#FBBF24", ft.Icons.INVENTORY_2_OUTLINED),
                kpi("AVANCE RECEPCIÓN", self.lbl_kpi_pct, "#A78BFA", ft.Icons.DONUT_LARGE_ROUNDED),
            ], spacing=10, run_spacing=10),
            ft.Container(padding=12, bgcolor=CARD, border_radius=8, border=ft.Border.all(1, BORDER),
                content=ft.Column([
                    ft.Row([ft.Text("BANDEJA DE TRASLADOS EN TRÁNSITO A CONCEPCIÓN", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
                        ft.Row([self.txt_buscar, boton_primario("ACTUALIZAR", ft.Icons.SYNC_ROUNDED, self.cargar_bandeja, "#0284C7")], wrap=True)],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
                    ft.Divider(color=BORDER, height=2), self.cont_ots], spacing=8))
        ], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

        self.sub_recepcion = ft.Column([
            ft.Container(padding=12, bgcolor="#0F172A", border_radius=8,
                content=ft.Row([
                    ft.Icon(ft.Icons.WAREHOUSE_ROUNDED, color="#5EEAD4", size=28),
                    ft.Column([self.lbl_ot, self.lbl_meta], spacing=2, expand=True),
                    boton_primario("VOLVER A BANDEJA", ft.Icons.ARROW_BACK_ROUNDED, lambda e: self.sel_sub_recepcion_ccp(0), "#475569")
                ], wrap=True)),
            ft.Container(padding=12, bgcolor=CARD, border_radius=8, border=ft.Border.all(1, BORDER),
                content=ft.Column([
                    ft.Text("1. ESCANEO Y VALIDACIÓN DE PALLET", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
                    ft.Row([self.txt_scan_lpn,
                        boton_primario("RECIBIR LPN", ft.Icons.QR_CODE_SCANNER_ROUNDED, self.procesar_lpn, TEAL)], wrap=True),
                    ft.Divider(color=BORDER, height=2), self.cont_lpns,
                    ft.Row([
                        boton_primario("CERRAR RECEPCIÓN CONFORME", ft.Icons.VERIFIED_ROUNDED, lambda e: self.cerrar_recepcion(False), "#047857"),
                        boton_primario("CERRAR CON DIFERENCIAS", ft.Icons.WARNING_AMBER_ROUNDED, lambda e: self.cerrar_recepcion(True), "#B45309"),
                    ], alignment=ft.MainAxisAlignment.END, wrap=True)
                ], spacing=9))
        ], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

        self.contenedor = ft.Container(content=self.sub_bandeja, expand=True)
        self.vista = ft.Container(
            padding=12, bgcolor=BG, expand=True,
            content=ft.Column([
                ft.Container(padding=ft.Padding.symmetric(horizontal=14, vertical=10), bgcolor="#222A2C",
                    border_radius=8, border=ft.Border.all(1, BORDER),
                    content=ft.Row([ft.Icon(ft.Icons.MOVE_TO_INBOX_ROUNDED, color=CYAN, size=23),
                        ft.Column([ft.Text("RECEPCIÓN DE TRASLADOS - CONCEPCIÓN", size=14.5, weight=ft.FontWeight.W_900, color=WHITE),
                            ft.Text("Control por OT y LPN: cajas, displays, unidades, lote y vencimiento", size=10.5, color=MUTED)], spacing=1)], spacing=10)),
                self.contenedor], spacing=10, expand=True))

    def _validar_bodega(self):
        actual = obtener_bodega_activa(self.page).upper().replace("Ó", "O")
        if "CONCEPCION" not in actual:
            notificar_global(self.page, "Módulo restringido exclusivamente a Bodega Concepción.", "#B91C1C")
            return False
        return True

    def _cargar_datos_ot(self):
        res_ov = supabase.table("netsuite_ordenes_venta").select("*").ilike("numero_ov", "OT-CCP-%").order("id", desc=True).limit(300).execute()
        res_pl = supabase.table("wms_packing_lists_fa").select("*").order("id", desc=True).limit(500).execute()
        mapa_pl = {}
        for pl in (res_pl.data or []):
            num = str(pl.get("numero_ov") or "").strip().upper()
            if not num: continue
            det = pl.get("detalle_json") or []
            if isinstance(det, str):
                try: det = json.loads(det)
                except Exception: det = []
            destino = mapa_pl.setdefault(num, [])
            claves = {(str(i.get("lpn_pallet") or i.get("lpn_consolidado") or "").upper(), normalizar_sku(i.get("sku")), normalizar_lote(i.get("lote")), fecha_a_iso(i.get("fecha_vencimiento_cl")), int(i.get("unidades_totales") or i.get("pickeado") or 0)) for i in destino}
            for raw in det:
                if not isinstance(raw, dict): continue
                item = dict(raw)
                clave = (str(item.get("lpn_pallet") or item.get("lpn_consolidado") or "").upper(), normalizar_sku(item.get("sku")), normalizar_lote(item.get("lote")), fecha_a_iso(item.get("fecha_vencimiento_cl")), int(item.get("unidades_totales") or item.get("pickeado") or 0))
                if clave not in claves: destino.append(item); claves.add(clave)
        return [dict(x) for x in (res_ov.data or [])], mapa_pl

    def cargar_bandeja(self, e=None):
        if not self._validar_bodega(): return
        q = (self.txt_buscar.value or "").strip().upper()
        try:
            ovs, mapa = self._cargar_datos_ot()
            filas = []; total_un = 0; total_lpn = 0; recibidos = 0
            for ov in ovs:
                estado = str(ov.get("estado_ns") or ov.get("estado") or "").upper()
                if estado not in ("EN_TRANSITO_CCP", "RECEPCION_CCP_EN_PROCESO", "RECIBIDO_CCP_CON_DIFERENCIAS"): continue
                num = str(ov.get("numero_ov") or "").upper()
                cli = str(ov.get("cliente_nombre") or "BODEGA CONCEPCIÓN")
                if q and q not in num and q not in cli.upper(): continue
                detalle = mapa.get(num, [])
                lpns = {str(x.get("lpn_pallet") or x.get("lpn_consolidado") or "").upper() for x in detalle if x.get("lpn_pallet") or x.get("lpn_consolidado")}
                un = sum(int(x.get("unidades_totales") or x.get("pickeado") or 0) for x in detalle)
                total_un += un; total_lpn += len(lpns)
                try:
                    rr = supabase.table("wms_recepcion_traslados_ccp").select("lpn, estado").eq("orden_id", ov["id"]).execute()
                    rec = {str(x.get("lpn") or "").upper() for x in (rr.data or []) if str(x.get("estado") or "").upper().startswith("RECIBIDO")}
                except Exception: rec = set()
                recibidos += len(rec)
                filas.append(ft.DataRow(cells=[
                    ft.DataCell(ft.Text(num, weight=ft.FontWeight.BOLD, color="#38BDF8")),
                    ft.DataCell(ft.Text("BODEGA CONCEPCIÓN")),
                    ft.DataCell(ft.Text(f"{len(rec)} / {len(lpns)}", color="#34D399")),
                    ft.DataCell(ft.Text(str(un), color="#FBBF24")),
                    ft.DataCell(crear_badge_estado(estado, "#FFFFFF", "#0F766E" if estado == "EN_TRANSITO_CCP" else "#92400E")),
                    ft.DataCell(boton_primario("RECIBIR", ft.Icons.MOVE_TO_INBOX_ROUNDED, lambda ev, o=ov, d=detalle, r=rec: self.iniciar_recepcion(o, d, r), "#0F766E", height_val=28)),
                ]))
            self.tabla_ots.rows = filas
            self.lbl_kpi_ot.value = str(len(filas)); self.lbl_kpi_lpn.value = f"{recibidos} / {total_lpn}"
            self.lbl_kpi_un.value = str(total_un); self.lbl_kpi_pct.value = f"{int(recibidos/max(1,total_lpn)*100)}%"
            self.page.update()
        except Exception as ex:
            notificar_global(self.page, f"Error cargando traslados CCP: {ex}", "#B91C1C")

    def iniciar_recepcion(self, ov, detalle, recibidos):
        if not self._validar_bodega(): return
        self.ot_activa = ov; self.lpns_recibidos = set(recibidos); self.pallets_esperados = {}
        for item in detalle:
            lpn = str(item.get("lpn_pallet") or item.get("lpn_consolidado") or "").upper()
            if lpn: self.pallets_esperados.setdefault(lpn, []).append(dict(item))
        self.lbl_ot.value = str(ov.get("numero_ov") or "OT-CCP").upper()
        self.lbl_meta.value = f"Origen: Bodega Santiago | Esperados: {len(self.pallets_esperados)} LPN | Recibidos: {len(self.lpns_recibidos)}"
        self._refrescar_tabla_lpns(); self.sel_sub_recepcion_ccp(1)
        try: supabase.table("netsuite_ordenes_venta").update({"estado_ns":"RECEPCION_CCP_EN_PROCESO"}).eq("id", ov["id"]).execute()
        except Exception: pass

    def _refrescar_tabla_lpns(self):
        filas=[]
        for lpn, items in self.pallets_esperados.items():
            estado = "RECIBIDO" if lpn in self.lpns_recibidos else "PENDIENTE"
            filas.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(lpn, weight=ft.FontWeight.BOLD, color="#38BDF8")),
                ft.DataCell(ft.Text(str(len({x.get('sku') for x in items})))),
                ft.DataCell(ft.Text(str(sum(int(x.get('cajas') or 0) for x in items)))),
                ft.DataCell(ft.Text(str(sum(int(x.get('displays') or 0) for x in items)))),
                ft.DataCell(ft.Text(str(sum(int(x.get('unidades_totales') or x.get('pickeado') or 0) for x in items)))),
                ft.DataCell(crear_badge_estado(estado, "#065F46" if estado=="RECIBIDO" else "#92400E", "#D1FAE5" if estado=="RECIBIDO" else "#FEF3C7")),
            ]))
        self.tabla_lpns.rows=filas; self.page.update()

    def procesar_lpn(self, e=None):
        if not self._validar_bodega() or not self.ot_activa: return
        lpn=(self.txt_scan_lpn.value or "").strip().upper(); self.txt_scan_lpn.value=""
        if lpn not in self.pallets_esperados:
            notificar_global(self.page, f"LPN {lpn} no pertenece a {self.lbl_ot.value}.", "#B91C1C"); return
        if lpn in self.lpns_recibidos:
            notificar_global(self.page, f"LPN {lpn} ya fue recibido. No se permite duplicar.", "#D97706"); return
        items=self.pallets_esperados[lpn]
        payload={
            "orden_id":self.ot_activa["id"], "numero_ot":self.lbl_ot.value, "lpn":lpn,
            "bodega_origen":"Bodega Santiago", "bodega_destino":"Bodega Concepcion", "estado":"RECIBIDO_CCP",
            "detalle_despachado":items, "detalle_recibido":items,
            "total_cajas_despachadas":sum(int(x.get("cajas") or 0) for x in items),
            "total_displays_despachados":sum(int(x.get("displays") or 0) for x in items),
            "total_unidades_despachadas":sum(int(x.get("unidades_totales") or x.get("pickeado") or 0) for x in items),
            "total_unidades_recibidas":sum(int(x.get("unidades_totales") or x.get("pickeado") or 0) for x in items),
            "usuario_recepcion":str(getattr(self.page,"usuario_actual","OPERADOR CCP")), "fecha_recepcion":datetime.now().isoformat(),
            "updated_at":datetime.now().isoformat(),
        }
        try:
            supabase.table("wms_recepcion_traslados_ccp").upsert(payload, on_conflict="numero_ot,lpn").execute()
            ok_ingreso = self._registrar_ingreso_en_ccp(lpn, items)
            if not ok_ingreso:
                notificar_global(self.page, f"LPN {lpn} recibido, pero no se pudo crear su registro de recepción en CCP. Revise conexión.", "#D97706")
            self.lpns_recibidos.add(lpn); self._refrescar_tabla_lpns()
            self.lbl_meta.value=f"Origen: Bodega Santiago | Esperados: {len(self.pallets_esperados)} LPN | Recibidos: {len(self.lpns_recibidos)}"
            notificar_global(self.page, f"LPN {lpn} recibido conforme.", "#047857")
        except Exception as ex: notificar_global(self.page, f"Error guardando recepción: {ex}", "#B91C1C")

    @staticmethod
    def _lote_y_venc_desde_item(item: dict):
        """Soporta packing nuevo (lote / fecha_vencimiento_cl) y antiguo ('lotes': 'LOTE / VENC (N UN)')."""
        lote = str(item.get("lote") or "").strip().upper()
        venc = item.get("fecha_vencimiento_cl")
        if not lote:
            texto = str(item.get("lotes") or "")
            texto = texto.split("]")[-1].split("(")[0].strip()
            partes = [x.strip() for x in texto.split(" / ")]
            lote = (partes[0] if partes and partes[0] else "S/L").upper()
            if not venc and len(partes) > 1 and partes[1].upper() not in ("", "S/F"):
                venc = partes[1]
        return (lote or "S/L"), (str(venc).strip() if venc and str(venc).strip().upper() != "S/F" else None)

    def _registrar_ingreso_en_ccp(self, lpn: str, items: list) -> bool:
        """Crea la recepción del LPN en Bodega Concepcion (función wms_cerrar_pallet_recepcion)
        para que el RF pueda hacer Putaway. Valida SKU, fechas y LPN en el servidor."""
        try:
            ya = supabase.table("registro_recepcion").select("id").eq("lpn", lpn).eq("bodega", "Bodega Concepcion").limit(1).execute()
            if ya.data:
                return True
        except Exception:
            pass
        lineas = []
        for it in items:
            sku = normalizar_sku(it.get("sku"))
            unid = int(it.get("unidades_totales") or it.get("pickeado") or 0)
            if not sku or unid <= 0:
                continue
            lote, venc = self._lote_y_venc_desde_item(it)
            try:
                fecha = fecha_a_date(venc) if venc else None
            except Exception:
                fecha = None  # fechas ilegibles del packing antiguo ("2028", "12/20/28") quedan sin vencimiento
            mult = max(1, int(it.get("multiplo_aplicado") or 1))
            cajas = int(it.get("cajas") or 0)
            if cajas * mult > unid:
                cajas = unid // mult
            lineas.append({
                "sku": sku, "lote": lote, "fecha_vencimiento": fecha.strftime("%d-%m-%Y") if fecha else None,
                "cajas": cajas, "multiplo": mult, "unidades_sueltas": unid - cajas * mult, "unidades_totales": unid,
            })
        if not lineas:
            return False
        try:
            supabase.rpc("wms_cerrar_pallet_recepcion", {
                "p_bodega": "Bodega Concepcion", "p_lpn": lpn, "p_lineas": lineas, "p_asn_id": None,
                "p_contenedor": self.lbl_ot.value, "p_usuario": str(getattr(self.page, "usuario_actual", "OPERADOR CCP")),
            }).execute()
            return True
        except Exception as ex:
            print(f"[WARN] Recepción CCP de {lpn}: {ex}")
            notificar_global(self.page, f"Recepción CCP {lpn}: {str(ex)[:160]}", "#B91C1C")
            return False

    def cerrar_recepcion(self, con_diferencias=False):
        if not self.ot_activa: return
        faltantes=set(self.pallets_esperados)-self.lpns_recibidos
        if faltantes and not con_diferencias:
            notificar_global(self.page, f"No se puede cerrar conforme: faltan {len(faltantes)} LPN.", "#B91C1C"); return
        estado="RECIBIDO_CCP_CON_DIFERENCIAS" if con_diferencias or faltantes else "RECIBIDO_CCP"
        try:
            supabase.table("netsuite_ordenes_venta").update({"estado_ns":estado}).eq("id",self.ot_activa["id"]).execute()
            notificar_global(self.page, f"{self.lbl_ot.value} cerrada como {estado}.", "#047857" if estado=="RECIBIDO_CCP" else "#B45309")
            self.ot_activa=None; self.pallets_esperados={}; self.lpns_recibidos=set(); self.sel_sub_recepcion_ccp(0); self.cargar_bandeja()
        except Exception as ex: notificar_global(self.page, f"Error cerrando recepción: {ex}", "#B91C1C")

    def sel_sub_recepcion_ccp(self, idx:int):
        if not self._validar_bodega(): return
        self.contenedor.content=self.sub_recepcion if idx==1 else self.sub_bandeja
        if idx==0: self.cargar_bandeja()
        self.page.update()

    def refrescar(self, e=None):
        self.cargar_bandeja(e)
