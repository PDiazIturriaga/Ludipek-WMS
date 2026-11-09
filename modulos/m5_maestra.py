import os
import json
import threading
from datetime import datetime
import pandas as pd
import flet as ft
from dependencias import *

RUTA_PERMISOS_LOCAL = "config_permisos_wms.json"
RUTA_MAESTRA_EXTRA = "config_maestra_extra.json"


class MaestraModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables

        # --- 1. PALETA OSCURA INDUSTRIAL ---
        BG_MODULO = "#1B2122"
        BG_CARD = "#262E30"
        BG_INPUT = "#1D2426"
        BG_DIGITAL = "#121718"
        BORDER_COLOR = "#3B484B"
        ACCENT_TEAL = "#527976"
        ACCENT_CYAN = "#38BDF8"
        ACCENT_BLUE = "#0284C7"
        ACCENT_PURPLE = "#8B5CF6"
        ACCENT_AMBER = "#F59E0B"
        ACCENT_GREEN = "#10B981"
        TEXT_WHITE = "#FFFFFF"
        TEXT_MUTED = "#94A3B8"

        # --- 2. CATÁLOGO DE MÓDULOS PC Y CELULAR (RF) ---
        MODULOS_PC_LISTA = [
            ("PC_DASHBOARD", "Dashboards & BI"),
            ("PC_RECEPCION", "Recepción (Ingresos PO)"),
            ("PC_ALMACENAMIENTO", "Almacenamiento (Putaway)"),
            ("PC_OLAS", "Olas & Packing"),
            ("PC_INVENTARIO", "Mov. Stock (Inventario)"),
            ("PC_ADMIN_MAESTRA", "Admin. Usuarios & Maestra SKU"),
            ("PC_IMPRESION", "Etiquetas & Impresión"),
        ]

        MODULOS_RF_LISTA = [
            ("RF_RECEPCION", "RF Recepción Andén"),
            ("RF_PUTAWAY", "RF Putaway (Ubicación)"),
            ("RF_PICKING", "RF Picking de Olas"),
            ("RF_REABASTECIMIENTO", "RF Reabastecimiento N1"),
            ("RF_INVENTARIO", "RF Auditoría & Conteo Cíclico"),
            ("RF_CONSULTA", "RF Consultor de Stock/LPN"),
        ]

        # --- 3. VARIABLES DE ESTADO ---
        lock_datos = threading.Lock()
        usuarios_db = []
        skus_db = []
        columnas_reales_maestra = set()
        columnas_reales_usuarios = set()
        id_usuario_editando = None
        sku_original_editando = None
        subvista_activa_idx = 0

        # --- 4. PERSISTENCIA AUXILIAR LOCAL (RESPALDO INMEDIATO) ---
        def leer_json_local(ruta: str) -> dict:
            if os.path.exists(ruta):
                try:
                    with open(ruta, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    return {}
            return {}

        def guardar_json_local(ruta: str, data: dict):
            try:
                with open(ruta, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        # --- 5. HELPERS VISUALES ---
        def notificar(texto: str, color: str = "#0284C7"):
            from dependencias import notificar_global
            notificar_global(self.page, texto, color)

        def tarjeta_dark(contenido, padding=14, expand_val=None, height_val=None, width_val=None):
            t = ft.Container(
                content=contenido, padding=padding, height=height_val, width=width_val, expand=expand_val,
                bgcolor=BG_CARD, border_radius=8, border=ft.Border.all(1, BORDER_COLOR),
                shadow=ft.BoxShadow(blur_radius=10, color="#40000000", offset=ft.Offset(0, 3)),
            )
            if isinstance(self.tarjetas_adaptables, list):
                self.tarjetas_adaptables.append(t)
            return t

        def texto_dark(label: str, width: int = None, expand=None, value: str = "", password: bool = False, on_change=None, icon=None):
            return ft.TextField(
                label=label, width=width, expand=expand, value=value, dense=True, text_size=12,
                password=password, can_reveal_password=password,
                color=TEXT_WHITE, bgcolor=BG_INPUT, border_color=BORDER_COLOR, focused_border_color=ACCENT_CYAN,
                label_style=ft.TextStyle(size=11, color=TEXT_MUTED),
                prefix_icon=icon,
                content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                on_change=on_change, border_radius=6,
            )

        def opt_w(key, text):
            return ft.DropdownOption(
                key=key, text=text,
                content=ft.Container(content=ft.Text(text, color=TEXT_WHITE, size=12), alignment=ft.Alignment.CENTER_LEFT),
            )

        def dropdown_dark(label: str, width: int = None, expand=None, value: str = None, options: list = None):
            return ft.Dropdown(
                label=label, width=width, expand=expand, value=value, options=options or [], dense=True,
                color=TEXT_WHITE, bgcolor=BG_INPUT, border_color=BORDER_COLOR, focused_border_color=ACCENT_CYAN,
                text_style=ft.TextStyle(size=12, color=TEXT_WHITE), label_style=ft.TextStyle(size=11, color=TEXT_MUTED),
                content_padding=ft.Padding.symmetric(horizontal=12, vertical=8), border_radius=6,
            )

        def crear_caja_digital(txt_control: ft.Text, etiqueta_inf: str, color_borde: str = "#6366F1", ancho: int = 92):
            return ft.Column(
                [
                    ft.Container(
                        width=ancho, height=56, bgcolor=BG_DIGITAL, border_radius=6,
                        border=ft.Border.all(1.5, color_borde), alignment=ft.Alignment.CENTER,
                        shadow=ft.BoxShadow(blur_radius=6, color="#33000000"), content=txt_control,
                    ),
                    ft.Text(etiqueta_inf, size=10, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4,
            )

        # =========================================================================
        # SECCIÓN A: GESTIÓN DE USUARIOS Y PERMISOS (PC & CELULAR RF)
        # =========================================================================
        lbl_modo_form_usr = ft.Text("MODO: CREAR NUEVO USUARIO", size=11, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN)
        txt_usr_login = texto_dark("Usuario / RUT (Ej: PDIAZ)", width=180, icon=ft.Icons.BADGE_OUTLINED)
        txt_usr_nombre = texto_dark("Nombre Completo (Ej: Patricio Díaz)", width=240, icon=ft.Icons.PERSON_OUTLINE)
        txt_usr_pass = texto_dark("Contraseña", width=165, password=True, icon=ft.Icons.LOCK_OUTLINE)
        dd_usr_rol = dropdown_dark(
            label="Rol Principal", width=185, value="OPERADOR RF",
            options=[
                opt_w("ADMIN", "ADMIN (Acceso Total)"),
                opt_w("SUPERVISOR", "SUPERVISOR BODEGA"),
                opt_w("OPERADOR RF", "OPERADOR RF (Piso)"),
                opt_w("AUDITOR", "AUDITOR INVENTARIO"),
                opt_w("CONSULTA", "SOLO CONSULTA"),
            ],
        )
        dd_usr_bodega = dropdown_dark(
            label="Bodega Asignada", width=185, value="Bodega Santiago",
            options=[
                opt_w("Bodega Santiago", "Bodega Santiago"),
                opt_w("Bodega Concepcion", "Bodega Concepcion"),
            ],
        )
        sw_usr_activo = ft.Switch(label="Usuario Activo", value=True, active_color=ACCENT_GREEN)
        txt_buscar_usr = texto_dark("Buscar usuario por código, nombre, rol o bodega...", expand=True, icon=ft.Icons.SEARCH_ROUNDED)

        checks_pc = {
            cod: ft.Checkbox(label=nom, value=True, active_color=ACCENT_CYAN, label_style=ft.TextStyle(size=11, color=TEXT_WHITE))
            for cod, nom in MODULOS_PC_LISTA
        }
        checks_rf = {
            cod: ft.Checkbox(label=nom, value=True, active_color=ACCENT_GREEN, label_style=ft.TextStyle(size=11, color=TEXT_WHITE))
            for cod, nom in MODULOS_RF_LISTA
        }

        lbl_kpi_usr_total = ft.Text("0", size=20, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_kpi_usr_activos = ft.Text("0", size=20, weight=ft.FontWeight.W_900, color=ACCENT_GREEN, font_family="Consolas")
        lbl_kpi_usr_admins = ft.Text("0", size=20, weight=ft.FontWeight.W_900, color=ACCENT_PURPLE, font_family="Consolas")
        lbl_kpi_usr_rf = ft.Text("0", size=20, weight=ft.FontWeight.W_900, color=ACCENT_AMBER, font_family="Consolas")

        tabla_usuarios = ft.DataTable(
            heading_row_color="#181E20", heading_row_height=34, data_row_min_height=34, data_row_max_height=42,
            column_spacing=12, data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("USUARIO", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("NOMBRE COMPLETO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("BODEGA", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_AMBER)),
                ft.DataColumn(ft.Text("ROL", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("ACCESO PC (TORRE)", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("ACCESO CELULAR (APP RF)", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_GREEN)),
                ft.DataColumn(ft.Text("ESTADO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ACCIONES", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )
        cont_tabla_usuarios = envolver_tabla_scroll(tabla_usuarios, 290)

        def aplicar_preset_permisos(tipo: str):
            if tipo == "ADMIN":
                for c in checks_pc.values(): c.value = True
                for c in checks_rf.values(): c.value = True
                dd_usr_rol.value = "ADMIN"
            elif tipo == "OPERADOR_RF":
                for c in checks_pc.values(): c.value = False
                for c in checks_rf.values(): c.value = True
                dd_usr_rol.value = "OPERADOR RF"
            elif tipo == "SUPERVISOR":
                for k, c in checks_pc.items():
                    c.value = (k != "PC_ADMIN_MAESTRA")
                for c in checks_rf.values(): c.value = True
                dd_usr_rol.value = "SUPERVISOR"
            page.update()

        def obtener_permisos_usuario(row_u: dict) -> tuple:
            u_key = str(row_u.get("usuario") or "").strip().upper()
            rol_u = str(row_u.get("rol") or "").strip().upper()
            mapa_local = leer_json_local(RUTA_PERMISOS_LOCAL)

            pc_raw = row_u.get("modulos_pc") or row_u.get("permisos_pc")
            rf_raw = row_u.get("modulos_rf") or row_u.get("permisos_rf")

            if pc_raw is not None or rf_raw is not None:
                pc_list = [x.strip() for x in str(pc_raw or "").split(",") if x.strip()]
                rf_list = [x.strip() for x in str(rf_raw or "").split(",") if x.strip()]
                return (pc_list, rf_list)

            if u_key in mapa_local:
                return (
                    mapa_local[u_key].get("modulos_pc", []),
                    mapa_local[u_key].get("modulos_rf", []),
                )

            if "ADMIN" in rol_u:
                return ([k for k, _ in MODULOS_PC_LISTA], [k for k, _ in MODULOS_RF_LISTA])
            elif "OPERADOR" in rol_u:
                return (["PC_RECEPCION", "PC_ALMACENAMIENTO", "PC_IMPRESION"], [k for k, _ in MODULOS_RF_LISTA])
            else:
                return ([k for k, _ in MODULOS_PC_LISTA if k != "PC_ADMIN_MAESTRA"], [k for k, _ in MODULOS_RF_LISTA])

        def limpiar_formulario_usuario(e=None):
            nonlocal id_usuario_editando
            id_usuario_editando = None
            lbl_modo_form_usr.value = "MODO: CREAR NUEVO USUARIO"
            lbl_modo_form_usr.color = ACCENT_CYAN
            txt_usr_login.value = ""
            txt_usr_nombre.value = ""
            txt_usr_pass.value = ""
            dd_usr_rol.value = "OPERADOR RF"
            dd_usr_bodega.value = "Bodega Santiago"
            sw_usr_activo.value = True
            for c in checks_pc.values(): c.value = True
            for c in checks_rf.values(): c.value = True
            page.update()

        def cargar_usuario_en_formulario(row_u: dict):
            nonlocal id_usuario_editando
            id_usuario_editando = row_u.get("id")
            u_log = str(row_u.get("usuario") or "").strip()
            lbl_modo_form_usr.value = f"MODO: EDITANDO USUARIO [{u_log}]"
            lbl_modo_form_usr.color = ACCENT_AMBER
            txt_usr_login.value = u_log
            txt_usr_nombre.value = str(row_u.get("nombre_completo") or "")
            txt_usr_pass.value = str(row_u.get("password") or "")
            rol_actual = str(row_u.get("rol") or "OPERADOR RF").strip().upper()
            opciones_roles_keys = [o.key for o in dd_usr_rol.options]
            if rol_actual not in opciones_roles_keys:
                dd_usr_rol.options.append(opt_w(rol_actual, rol_actual))
            dd_usr_rol.value = rol_actual

            bodega_actual = str(row_u.get("bodega") or "Bodega Santiago").strip()
            opciones_bod_keys = [o.key for o in dd_usr_bodega.options]
            if bodega_actual not in opciones_bod_keys:
                dd_usr_bodega.options.append(opt_w(bodega_actual, bodega_actual))
            dd_usr_bodega.value = bodega_actual

            sw_usr_activo.value = bool(row_u.get("activo", True))

            pc_list, rf_list = obtener_permisos_usuario(row_u)
            for k, chk in checks_pc.items():
                chk.value = (k in pc_list)
            for k, chk in checks_rf.items():
                chk.value = (k in rf_list)
            page.update()

        def renderizar_tabla_usuarios(e=None):
            filtro = (txt_buscar_usr.value or "").strip().upper()
            nuevas_filas = []
            activos_cnt = 0
            admins_cnt = 0
            rf_cnt = 0

            copia_usuarios = list(usuarios_db)
            for u in copia_usuarios:
                u_log = str(u.get("usuario") or "").strip()
                u_nom = str(u.get("nombre_completo") or "").strip()
                u_bod = str(u.get("bodega") or "Bodega Santiago").strip()
                u_rol = str(u.get("rol") or "OPERADOR").strip().upper()
                es_act = bool(u.get("activo", True))

                if es_act:
                    activos_cnt += 1
                if "ADMIN" in u_rol:
                    admins_cnt += 1

                pc_list, rf_list = obtener_permisos_usuario(u)
                if rf_list:
                    rf_cnt += 1

                if filtro and not any(filtro in s.upper() for s in (u_log, u_nom, u_rol, u_bod)):
                    continue

                badge_est = (
                    crear_badge_estado("ACTIVO", "#065F46", "#D1FAE5")
                    if es_act
                    else crear_badge_estado("INACTIVO", "#991B1B", "#FEE2E2")
                )
                es_ccp = "CONCEPCION" in u_bod.upper()
                badge_bod = crear_badge_estado(
                    u_bod,
                    "#92400E" if es_ccp else "#065F46",
                    "#FEF3C7" if es_ccp else "#D1FAE5",
                )

                txt_pc_resumen = f"🖥️ {len(pc_list)}/{len(MODULOS_PC_LISTA)} Módulos PC"
                txt_rf_resumen = f"📱 {len(rf_list)}/{len(MODULOS_RF_LISTA)} Módulos RF"

                def toggle_estado_usr(ev, item_u=u):
                    nuevo_est = not bool(item_u.get("activo", True))
                    try:
                        if item_u.get("id") is not None:
                            supabase.table("wms_usuarios").update({"activo": nuevo_est}).eq("id", item_u["id"]).execute()
                        else:
                            supabase.table("wms_usuarios").update({"activo": nuevo_est}).eq("usuario", item_u.get("usuario")).execute()
                        item_u["activo"] = nuevo_est
                        notificar(f"Estado de {item_u.get('usuario')} actualizado.", "#047857")
                        renderizar_tabla_usuarios()
                    except Exception as ex_t:
                        notificar(f"Error cambiando estado: {ex_t}", "#B91C1C")

                nuevas_filas.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(u_log, weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                            ft.DataCell(ft.Text(u_nom[:26], size=11, color=TEXT_WHITE)),
                            ft.DataCell(badge_bod),
                            ft.DataCell(crear_badge_estado(u_rol, "#1E3A8A" if "ADMIN" not in u_rol else "#581C87", "#DBEAFE")),
                            ft.DataCell(ft.Text(txt_pc_resumen, size=11, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN if pc_list else TEXT_MUTED)),
                            ft.DataCell(ft.Text(txt_rf_resumen, size=11, weight=ft.FontWeight.BOLD, color=ACCENT_GREEN if rf_list else TEXT_MUTED)),
                            ft.DataCell(badge_est),
                            ft.DataCell(
                                ft.Row(
                                    [
                                        boton_primario("EDITAR / PERMISOS", ft.Icons.EDIT_OUTLINED, lambda ev, it=u: cargar_usuario_en_formulario(it), ACCENT_BLUE, height_val=26),
                                        boton_primario("ACT/DES", ft.Icons.POWER_SETTINGS_NEW_ROUNDED, toggle_estado_usr, "#475569", height_val=26),
                                    ],
                                    spacing=6,
                                )
                            ),
                        ]
                    )
                )

            tabla_usuarios.rows = nuevas_filas
            lbl_kpi_usr_total.value = str(len(copia_usuarios))
            lbl_kpi_usr_activos.value = str(activos_cnt)
            lbl_kpi_usr_admins.value = str(admins_cnt)
            lbl_kpi_usr_rf.value = str(rf_cnt)
            page.update()

        txt_buscar_usr.on_change = renderizar_tabla_usuarios

        def cargar_usuarios_supabase():
            nonlocal usuarios_db, columnas_reales_usuarios
            with lock_datos:
                try:
                    res = supabase.table("wms_usuarios").select("*").order("id").execute()
                    usuarios_db = res.data or []
                    if usuarios_db:
                        columnas_reales_usuarios = set(usuarios_db[0].keys())
                except Exception:
                    try:
                        res = supabase.table("wms_usuarios").select("*").execute()
                        usuarios_db = res.data or []
                    except Exception:
                        usuarios_db = []
            renderizar_tabla_usuarios()

        def guardar_usuario_wms(e=None):
            nonlocal id_usuario_editando
            u_log = (txt_usr_login.value or "").strip().upper()
            u_nom = (txt_usr_nombre.value or "").strip()
            u_pass = (txt_usr_pass.value or "").strip()
            u_rol = (dd_usr_rol.value or "OPERADOR RF").strip()
            u_bod = (dd_usr_bodega.value or "Bodega Santiago").strip()
            u_act = bool(sw_usr_activo.value)

            if not u_log or not u_nom or not u_pass:
                notificar("Complete Usuario, Nombre Completo y Contraseña.", "#D97706")
                return

            pc_sel = [k for k, chk in checks_pc.items() if chk.value]
            rf_sel = [k for k, chk in checks_rf.items() if chk.value]

            # 1. Guardar permisos y bodega en JSON local
            mapa_local = leer_json_local(RUTA_PERMISOS_LOCAL)
            mapa_local[u_log] = {
                "modulos_pc": pc_sel,
                "modulos_rf": rf_sel,
                "rol": u_rol,
                "bodega": u_bod,
                "updated_at": datetime.now().isoformat(),
            }
            guardar_json_local(RUTA_PERMISOS_LOCAL, mapa_local)

            # 2. Guardar o actualizar en Supabase (incluyendo la columna bodega)
            payload_base = {
                "usuario": u_log,
                "nombre_completo": u_nom,
                "password": u_pass,
                "rol": u_rol,
                "bodega": u_bod,
                "activo": u_act,
            }
            payload_ext = dict(payload_base)
            payload_ext["modulos_pc"] = ",".join(pc_sel)
            payload_ext["modulos_rf"] = ",".join(rf_sel)

            guardado_ok = False
            try:
                if id_usuario_editando is not None:
                    try:
                        supabase.table("wms_usuarios").update(payload_ext).eq("id", id_usuario_editando).execute()
                    except Exception:
                        supabase.table("wms_usuarios").update(payload_base).eq("id", id_usuario_editando).execute()
                    guardado_ok = True
                else:
                    existentes = [x for x in usuarios_db if str(x.get("usuario") or "").strip().upper() == u_log]
                    if existentes:
                        id_ex = existentes[0].get("id")
                        try:
                            supabase.table("wms_usuarios").update(payload_ext).eq("id", id_ex).execute()
                        except Exception:
                            supabase.table("wms_usuarios").update(payload_base).eq("id", id_ex).execute()
                    else:
                        try:
                            supabase.table("wms_usuarios").insert(payload_ext).execute()
                        except Exception:
                            supabase.table("wms_usuarios").insert(payload_base).execute()
                    guardado_ok = True
            except Exception as ex_u:
                notificar(f"Error guardando en wms_usuarios: {ex_u}", "#B91C1C")
                return

            if guardado_ok:
                notificar(f"Usuario [{u_log}] guardado en {u_bod}.", "#047857")
                limpiar_formulario_usuario()
                cargar_usuarios_supabase()

        # =========================================================================
        # SECCIÓN B: CATÁLOGO MAESTRO DE SKUs (CORREGIDO PARA CONECTAR CON CELULAR)
        # =========================================================================
        lbl_modo_form_sku = ft.Text("MODO: CREAR / MODIFICAR FICHA MAESTRA DE SKU", size=11, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN)
        txt_sku_codigo = texto_dark("Código SKU (Ej: ALUC15)", width=155, icon=ft.Icons.QR_CODE_ROUNDED)
        txt_sku_desc = texto_dark("Descripción Completa del Producto", width=310, icon=ft.Icons.DESCRIPTION_OUTLINED)
        txt_sku_ean = texto_dark("EAN / Código Barra / DUN14", width=175, icon=ft.Icons.BARCODE_READER)
        txt_sku_multiplo = texto_dark("Unid. x Caja (Múltiplo)", width=155, value="1", icon=ft.Icons.APPS_ROUNDED)
        txt_sku_cajas_pallet = texto_dark("Cajas x Pallet", width=135, value="40", icon=ft.Icons.LAYERS_OUTLINED)
        txt_sku_peso = texto_dark("Peso (Kg)", width=120, value="1.0", icon=ft.Icons.SCALE_OUTLINED)
        txt_sku_ubic_pick = texto_dark("Ubic. Picking (Ej: A-01-01)", width=165, icon=ft.Icons.PLACE_OUTLINED)
        dd_sku_categoria = dropdown_dark(
            label="Categoría / Marca / Canal", width=175, value="ESTANDAR",
            options=[
                opt_w("ESTANDAR", "ESTÁNDAR (Normal)"),
                opt_w("FARMACIA (-FA)", "FARMACIA (-FA)"),
                opt_w("BOEHRINGER", "BOEHRINGER (Farma)"),
                opt_w("ALIMENTO", "ALIMENTO MASCOTAS"),
                opt_w("ACCESORIOS", "ACCESORIOS / OTROS"),
            ],
        )

        txt_buscar_sku = texto_dark("Buscar en Maestra por SKU, Descripción, EAN o Marca...", expand=True, icon=ft.Icons.SEARCH_ROUNDED)

        lbl_kpi_sku_total = ft.Text("0", size=20, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_kpi_sku_farma = ft.Text("0", size=20, weight=ft.FontWeight.W_900, color=ACCENT_AMBER, font_family="Consolas")
        lbl_kpi_sku_con_multiplo = ft.Text("0", size=20, weight=ft.FontWeight.W_900, color=ACCENT_GREEN, font_family="Consolas")

        tabla_maestra_skus = ft.DataTable(
            heading_row_color="#181E20", heading_row_height=34, data_row_min_height=32, data_row_max_height=40,
            column_spacing=14, data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("SKU", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("DESCRIPCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("EAN / CÓDIGO BARRAS", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("UNID. MÚLTIPLO (UxC)", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_GREEN)),
                ft.DataColumn(ft.Text("CAJAS x PALLET", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("PESO (KG)", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("MARCA / CAT", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("UBIC. PICKING", weight=ft.FontWeight.BOLD, size=10, color=TEXT_MUTED)),
                ft.DataColumn(ft.Text("ACCIÓN", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
            ],
            rows=[],
        )
        cont_tabla_skus = envolver_tabla_scroll(tabla_maestra_skus, 320)

        def extraer_datos_completos_sku(r: dict, extra_map: dict) -> dict:
            sku_c = str(r.get("sku") or r.get("codigo") or "").strip().upper()
            ext = extra_map.get(sku_c, {})
            desc_c = str(r.get("descripcion") or r.get("nombre") or ext.get("descripcion") or "").strip()
            
            # Unificación con codigo_barras de main.dart
            ean_c = str(r.get("codigo_barras") or r.get("ean") or r.get("codigo_barra") or r.get("dun14") or ext.get("ean") or "-").strip()
            
            mult_c = (
                r.get("multiplo")
                or r.get("unidades_por_caja")
                or r.get("unidades_multiplos")
                or r.get("uxc")
                or r.get("factor_empaque")
                or ext.get("multiplo")
                or 1
            )
            cajas_pal = (
                r.get("cajas_por_pallet")
                or r.get("pallet_cajas")
                or r.get("unidades_pallet")
                or ext.get("cajas_por_pallet")
                or 40
            )
            peso_c = (
                r.get("peso_kg")
                or r.get("peso")
                or r.get("peso_unitario")
                or ext.get("peso")
                or 0.0
            )
            # Unificación de marca y categoría con el celular
            marca_c = str(
                r.get("marca")
                or r.get("categoria")
                or r.get("familia")
                or r.get("canal")
                or ext.get("categoria")
                or ("FARMACIA (-FA)" if "-FA" in sku_c else "ESTANDAR")
            ).strip().upper()
            
            ubic_p = str(
                r.get("ubicacion_picking_fija")
                or r.get("ubicacion_picking")
                or r.get("ubicacion_sugerida")
                or r.get("ubicacion")
                or ext.get("ubicacion_picking")
                or "-"
            ).strip().upper()
            
            return {
                "raw": r,
                "sku": sku_c,
                "descripcion": desc_c,
                "ean": ean_c,
                "multiplo": int(float(mult_c or 1)),
                "cajas_por_pallet": int(float(cajas_pal or 40)),
                "peso": float(peso_c or 0.0),
                "marca_cat": marca_c,
                "ubicacion_picking": ubic_p,
            }

        def cargar_sku_en_formulario(info_s: dict):
            nonlocal sku_original_editando
            sku_original_editando = info_s["sku"]
            lbl_modo_form_sku.value = f"MODO: EDITANDO SKU [{info_s['sku']}]"
            lbl_modo_form_sku.color = ACCENT_AMBER
            txt_sku_codigo.value = info_s["sku"]
            txt_sku_desc.value = info_s["descripcion"]
            txt_sku_ean.value = "" if info_s["ean"] == "-" else info_s["ean"]
            txt_sku_multiplo.value = str(info_s["multiplo"])
            txt_sku_cajas_pallet.value = str(info_s["cajas_por_pallet"])
            txt_sku_peso.value = str(info_s["peso"])
            txt_sku_ubic_pick.value = "" if info_s["ubicacion_picking"] == "-" else info_s["ubicacion_picking"]
            cat_val = info_s["marca_cat"]
            if cat_val not in [o.key for o in dd_sku_categoria.options]:
                dd_sku_categoria.options.append(opt_w(cat_val, cat_val))
            dd_sku_categoria.value = cat_val
            page.update()

        def limpiar_formulario_sku(e=None):
            nonlocal sku_original_editando
            sku_original_editando = None
            lbl_modo_form_sku.value = "MODO: CREAR / MODIFICAR FICHA MAESTRA DE SKU"
            lbl_modo_form_sku.color = ACCENT_CYAN
            txt_sku_codigo.value = ""
            txt_sku_desc.value = ""
            txt_sku_ean.value = ""
            txt_sku_multiplo.value = "1"
            txt_sku_cajas_pallet.value = "40"
            txt_sku_peso.value = "1.0"
            txt_sku_ubic_pick.value = ""
            dd_sku_categoria.value = "ESTANDAR"
            page.update()

        def renderizar_tabla_maestra(e=None):
            filtro = (txt_buscar_sku.value or "").strip().upper()
            extra_map = leer_json_local(RUTA_MAESTRA_EXTRA)
            copia_skus = list(skus_db)

            nuevas_filas = []
            farma_cnt = 0
            mult_cnt = 0

            for r in copia_skus:
                info = extraer_datos_completos_sku(r, extra_map)
                if not info["sku"]:
                    continue
                if "FARMACIA" in info["marca_cat"] or "BOEHRINGER" in info["marca_cat"] or "-FA" in info["sku"]:
                    farma_cnt += 1
                try:
                    if int(float(info["multiplo"] or 1)) > 1:
                        mult_cnt += 1
                except Exception:
                    pass

                if filtro and not any(filtro in str(v).upper() for v in (info["sku"], info["descripcion"], info["ean"], info["marca_cat"])):
                    continue

                if len(nuevas_filas) < 300:
                    es_fa = "FARMACIA" in info["marca_cat"] or "BOEHRINGER" in info["marca_cat"] or "-FA" in info["sku"]
                    badge_cat = (
                        crear_badge_estado("FARMACIA (-FA)", "#92400E", "#FEF3C7")
                        if es_fa
                        else crear_badge_estado(info["marca_cat"][:14], "#1E3A8A", "#DBEAFE")
                    )
                    nuevas_filas.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(info["sku"], weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(info["descripcion"][:38], size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(info["ean"], size=11, color=TEXT_MUTED)),
                                ft.DataCell(ft.Text(f"{info['multiplo']} UN/Caja", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_GREEN)),
                                ft.DataCell(ft.Text(f"{info['cajas_por_pallet']} Cajas", size=11, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(f"{info['peso']} kg", size=11, color=ACCENT_CYAN)),
                                ft.DataCell(badge_cat),
                                ft.DataCell(ft.Text(info["ubicacion_picking"], size=11, color=TEXT_MUTED)),
                                ft.DataCell(
                                    boton_primario(
                                        "EDITAR SKU",
                                        ft.Icons.EDIT_NOTE_ROUNDED,
                                        lambda ev, inf=info: cargar_sku_en_formulario(inf),
                                        ACCENT_BLUE,
                                        height_val=26,
                                    )
                                ),
                            ]
                        )
                    )

            tabla_maestra_skus.rows = nuevas_filas
            lbl_kpi_sku_total.value = str(len(copia_skus))
            lbl_kpi_sku_farma.value = str(farma_cnt)
            lbl_kpi_sku_con_multiplo.value = str(mult_cnt)
            page.update()

        txt_buscar_sku.on_change = renderizar_tabla_maestra

        def cargar_maestra_skus(e=None):
            nonlocal skus_db, columnas_reales_maestra
            with lock_datos:
                acumulado = []
                paso = 1000
                for offset in range(0, 5000, paso):
                    try:
                        res = supabase.table("maestra_sku").select("*").range(offset, offset + paso - 1).execute()
                        lote = res.data or []
                        acumulado.extend(lote)
                        if len(lote) < paso:
                            break
                    except Exception:
                        break
                skus_db = acumulado
                if skus_db:
                    columnas_reales_maestra = set(skus_db[0].keys())
            renderizar_tabla_maestra()

        def guardar_sku_maestra(e=None):
            sku_c = (txt_sku_codigo.value or "").strip().upper()
            desc_c = (txt_sku_desc.value or "").strip()
            ean_c = (txt_sku_ean.value or "").strip().upper()
            ubic_p = (txt_sku_ubic_pick.value or "").strip().upper()
            cat_c = (dd_sku_categoria.value or "ESTANDAR").strip().upper()

            if not sku_c or not desc_c:
                notificar("El Código SKU y la Descripción son obligatorios.", "#D97706")
                return

            try:
                mult_val = int(float((txt_sku_multiplo.value or "1").replace(",", ".")))
            except Exception:
                mult_val = 1
            try:
                cajas_val = int(float((txt_sku_cajas_pallet.value or "40").replace(",", ".")))
            except Exception:
                cajas_val = 40
            try:
                peso_val = round(float((txt_sku_peso.value or "0").replace(",", ".")), 3)
            except Exception:
                peso_val = 0.0

            # Guardar respaldo extra local
            extra_map = leer_json_local(RUTA_MAESTRA_EXTRA)
            extra_map[sku_c] = {
                "descripcion": desc_c,
                "ean": ean_c or sku_c,
                "multiplo": mult_val,
                "cajas_por_pallet": cajas_val,
                "peso": peso_val,
                "categoria": cat_c,
                "ubicacion_picking": ubic_p or "-",
                "updated_at": datetime.now().isoformat(),
            }
            guardar_json_local(RUTA_MAESTRA_EXTRA, extra_map)

            # Payload unificado 100% compatible con main.dart (codigo_barras, marca, multiplicadores)
            payload_supa = {
                "sku": sku_c,
                "descripcion": desc_c,
                "codigo_barras": ean_c if ean_c else sku_c,
                "multiplo": mult_val,
                "marca": cat_c,
                "ubicacion_picking_fija": ubic_p if ubic_p else "-",
                "peso_kg": peso_val,
            }

            guardado_ok = False
            try:
                supabase.table("maestra_sku").upsert(payload_supa, on_conflict="sku").execute()
                guardado_ok = True
            except Exception as ex_up:
                # Intento de respaldo con nombres alternativos de columnas si la BD es mixta
                try:
                    payload_alt = {
                        "sku": sku_c,
                        "descripcion": desc_c,
                        "ean": ean_c if ean_c else sku_c,
                        "unidades_por_caja": mult_val,
                        "categoria": cat_c,
                        "ubicacion_picking": ubic_p,
                    }
                    supabase.table("maestra_sku").upsert(payload_alt, on_conflict="sku").execute()
                    guardado_ok = True
                except Exception as ex_alt:
                    notificar(f"Error guardando en Supabase: {ex_up}", "#B91C1C")
                    return

            if guardado_ok:
                notificar(f"Ficha Maestra de SKU [{sku_c}] guardada y sincronizada.", "#047857")
                limpiar_formulario_sku()
                cargar_maestra_skus()

        def exportar_maestra_excel(e=None):
            if not skus_db:
                notificar("No hay SKUs cargados para exportar.", "#D97706")
                return
            try:
                os.makedirs("reportes_recepcion", exist_ok=True)
                extra_map = leer_json_local(RUTA_MAESTRA_EXTRA)
                filas = [extraer_datos_completos_sku(r, extra_map) for r in skus_db]
                for f in filas:
                    f.pop("raw", None)
                df_exp = pd.DataFrame(filas)
                ruta = os.path.join("reportes_recepcion", f"Maestra_SKU_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
                df_exp.to_excel(ruta, index=False)
                descargar_o_abrir_archivo(self.page, ruta)
                notificar(f"Catálogo Maestro exportado: {ruta}", "#047857")
            except Exception as ex:
                notificar(f"Error exportando Maestra: {ex}", "#B91C1C")

        # =========================================================================
        # SECCIÓN C: VISTAS DEL MÓDULO (ADMINISTRACIÓN USUARIOS vs MAESTRA SKU)
        # =========================================================================
        vista_maestra_skus = ft.Column(
            [
                ft.Row(
                    [
                        tarjeta_dark(
                            ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, color=ACCENT_CYAN, size=18),
                                            ft.Text("EDITOR INTEGRAL DE MAESTRA DE SKUs (CREAR / MODIFICAR)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                                            ft.Container(expand=True),
                                            lbl_modo_form_sku,
                                        ],
                                        spacing=8,
                                    ),
                                    ft.Divider(color=BORDER_COLOR, height=4),
                                    ft.Row(
                                        [
                                            txt_sku_codigo,
                                            txt_sku_desc,
                                            txt_sku_ean,
                                            txt_sku_multiplo,
                                            txt_sku_cajas_pallet,
                                            txt_sku_peso,
                                            dd_sku_categoria,
                                            txt_sku_ubic_pick,
                                        ],
                                        spacing=8,
                                        wrap=True,
                                    ),
                                    ft.Row(
                                        [
                                            boton_primario("GUARDAR / ACTUALIZAR SKU", ft.Icons.SAVE_ROUNDED, guardar_sku_maestra, "#047857", height_val=32),
                                            boton_primario("LIMPIAR FORMULARIO", ft.Icons.CLEAR_ALL_ROUNDED, limpiar_formulario_sku, "#475569", height_val=32),
                                            boton_primario("EXPORTAR MAESTRA (.XLSX)", ft.Icons.TABLE_VIEW_ROUNDED, exportar_maestra_excel, ACCENT_TEAL, height_val=32),
                                        ],
                                        spacing=10,
                                    ),
                                ],
                                spacing=8,
                            ),
                            expand_val=True,
                        ),
                        tarjeta_dark(
                            ft.Column(
                                [
                                    ft.Text("RESUMEN CATÁLOGO SKU", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                                    ft.Row(
                                        [
                                            crear_caja_digital(lbl_kpi_sku_total, "Total SKUs", ACCENT_CYAN, 95),
                                            crear_caja_digital(lbl_kpi_sku_farma, "SKUs Farmacia", ACCENT_AMBER, 95),
                                            crear_caja_digital(lbl_kpi_sku_con_multiplo, "Con Múltiplo", ACCENT_GREEN, 95),
                                        ],
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    ),
                                ],
                                spacing=8,
                            ),
                            width_val=335,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text("CATÁLOGO MAESTRO DE PRODUCTOS (CLIC EN EDITAR PARA MODIFICAR CUALQUIER DATO)", size=12, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
                                    txt_buscar_sku,
                                ],
                                spacing=12,
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Divider(color=BORDER_COLOR, height=1),
                            cont_tabla_skus,
                        ],
                        spacing=8,
                    )
                ),
            ],
            spacing=10,
        )

        vista_admin_usuarios = ft.Column(
            [
                ft.Row(
                    [
                        tarjeta_dark(
                            ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Icon(ft.Icons.MANAGE_ACCOUNTS_ROUNDED, color=ACCENT_CYAN, size=20),
                                            ft.Text("CREAR / MODIFICAR USUARIOS Y PERMISOS DE ACCESO (PC & CELULAR RF)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                                            ft.Container(expand=True),
                                            lbl_modo_form_usr,
                                        ],
                                        spacing=8,
                                    ),
                                    ft.Divider(color=BORDER_COLOR, height=4),
                                    ft.Row(
                                        [
                                            txt_usr_login,
                                            txt_usr_nombre,
                                            txt_usr_pass,
                                            dd_usr_rol,
                                            dd_usr_bodega,
                                            sw_usr_activo,
                                        ],
                                        spacing=10,
                                        wrap=True,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                    ft.Row(
                                        [
                                            ft.Container(
                                                expand=True,
                                                padding=10,
                                                bgcolor="#181E20",
                                                border_radius=6,
                                                border=ft.Border.all(1, ACCENT_CYAN),
                                                content=ft.Column(
                                                    [
                                                        ft.Row(
                                                            [
                                                                ft.Icon(ft.Icons.DESKTOP_WINDOWS_ROUNDED, color=ACCENT_CYAN, size=16),
                                                                ft.Text("ACCESO A MÓDULOS DE PC (TORRE DE CONTROL):", size=11, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
                                                            ],
                                                            spacing=6,
                                                        ),
                                                        ft.Row(list(checks_pc.values()), wrap=True, spacing=12, run_spacing=2),
                                                    ],
                                                    spacing=4,
                                                ),
                                            ),
                                            ft.Container(
                                                expand=True,
                                                padding=10,
                                                bgcolor="#181E20",
                                                border_radius=6,
                                                border=ft.Border.all(1, ACCENT_GREEN),
                                                content=ft.Column(
                                                    [
                                                        ft.Row(
                                                            [
                                                                ft.Icon(ft.Icons.PHONE_ANDROID_ROUNDED, color=ACCENT_GREEN, size=16),
                                                                ft.Text("ACCESO A MÓDULOS DE CELULAR (APP MÓVIL RF):", size=11, weight=ft.FontWeight.BOLD, color=ACCENT_GREEN),
                                                            ],
                                                            spacing=6,
                                                        ),
                                                        ft.Row(list(checks_rf.values()), wrap=True, spacing=12, run_spacing=2),
                                                    ],
                                                    spacing=4,
                                                ),
                                            ),
                                        ],
                                        spacing=10,
                                        vertical_alignment=ft.CrossAxisAlignment.START,
                                    ),
                                    ft.Row(
                                        [
                                            boton_primario("GUARDAR USUARIO Y PERMISOS", ft.Icons.SAVE_ROUNDED, guardar_usuario_wms, "#047857", height_val=34),
                                            boton_primario("NUEVO / LIMPIAR", ft.Icons.PERSON_ADD_ALT_1_ROUNDED, limpiar_formulario_usuario, "#475569", height_val=34),
                                            boton_primario("PERFIL ADMIN TOTAL", ft.Icons.SECURITY_ROUNDED, lambda e: aplicar_preset_permisos("ADMIN"), ACCENT_PURPLE, height_val=30),
                                            boton_primario("PERFIL SOLO CELULAR RF", ft.Icons.SMARTPHONE_ROUNDED, lambda e: aplicar_preset_permisos("OPERADOR_RF"), ACCENT_BLUE, height_val=30),
                                            boton_primario("PERFIL SUPERVISOR", ft.Icons.SUPERVISOR_ACCOUNT_ROUNDED, lambda e: aplicar_preset_permisos("SUPERVISOR"), ACCENT_TEAL, height_val=30),
                                        ],
                                        spacing=8,
                                        wrap=True,
                                    ),
                                ],
                                spacing=8,
                            ),
                            expand_val=True,
                        ),
                        tarjeta_dark(
                            ft.Column(
                                [
                                    ft.Text("KPI USUARIOS WMS", size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                                    ft.Row(
                                        [
                                            crear_caja_digital(lbl_kpi_usr_total, "Total Usuarios", ACCENT_CYAN, 88),
                                            crear_caja_digital(lbl_kpi_usr_activos, "Activos", ACCENT_GREEN, 88),
                                        ],
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    ),
                                    ft.Row(
                                        [
                                            crear_caja_digital(lbl_kpi_usr_admins, "Admins PC", ACCENT_PURPLE, 88),
                                            crear_caja_digital(lbl_kpi_usr_rf, "Con App RF", ACCENT_AMBER, 88),
                                        ],
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    ),
                                ],
                                spacing=8,
                            ),
                            width_val=220,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                tarjeta_dark(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text("NÓMINA DE USUARIOS WMS Y PERMISOS ASIGNADOS (CLIC EN EDITAR PARA MODIFICAR)", size=12, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN),
                                    txt_buscar_usr,
                                ],
                                spacing=12,
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Divider(color=BORDER_COLOR, height=1),
                            cont_tabla_usuarios,
                        ],
                        spacing=8,
                    )
                ),
            ],
            spacing=10,
        )

        contenedor_subvista = ft.Container(content=vista_admin_usuarios)

        btn_tab_usuarios = ft.Container(
            padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            bgcolor=ACCENT_TEAL, border_radius=6, border=ft.Border.all(1.5, ACCENT_CYAN), ink=True,
            content=ft.Row([ft.Icon(ft.Icons.MANAGE_ACCOUNTS_ROUNDED, color=TEXT_WHITE, size=16), ft.Text("1. ADMINISTRACIÓN DE USUARIOS Y ACCESOS (PC / RF)", size=11, weight=ft.FontWeight.BOLD, color=TEXT_WHITE)], spacing=6),
        )
        btn_tab_maestra = ft.Container(
            padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            bgcolor="#181E20", border_radius=6, border=ft.Border.all(1, BORDER_COLOR), ink=True,
            content=ft.Row([ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, color=ACCENT_CYAN, size=16), ft.Text("2. MAESTRA INTEGRAL DE SKUs (PESO, MÚLTIPLOS, EAN)", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED)], spacing=6),
        )

        def cambiar_subvista_admin(idx: int):
            nonlocal subvista_activa_idx
            idx_limpio = 0 if idx == 0 else 1
            subvista_activa_idx = idx_limpio
            contenedor_subvista.content = [vista_admin_usuarios, vista_maestra_skus][idx_limpio]

            for i_b, b_ctrl in [(0, btn_tab_usuarios), (1, btn_tab_maestra)]:
                activo = (i_b == idx_limpio)
                b_ctrl.bgcolor = ACCENT_TEAL if activo else "#181E20"
                b_ctrl.border = ft.Border.all(1.5 if activo else 1, ACCENT_CYAN if activo else BORDER_COLOR)
                b_ctrl.content.controls[1].color = TEXT_WHITE if activo else TEXT_MUTED
            page.update()

        btn_tab_usuarios.on_click = lambda e: cambiar_subvista_admin(0)
        btn_tab_maestra.on_click = lambda e: cambiar_subvista_admin(1)

        def recargar_todo_admin_maestra(e=None):
            cargar_usuarios_supabase()
            cargar_maestra_skus()

        barra_titulo = ft.Container(
            padding=ft.Padding.symmetric(horizontal=16, vertical=10), bgcolor="#222A2C", border_radius=8, border=ft.Border.all(1, BORDER_COLOR),
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.ADMIN_PANEL_SETTINGS_OUTLINED, color=ACCENT_CYAN, size=22),
                            ft.Text("ADMINISTRACIÓN DE SISTEMA, PERMISOS (PC/RF) & MAESTRA DE SKUs", size=14, weight=ft.FontWeight.W_900, color=TEXT_WHITE),
                        ],
                        spacing=8,
                    ),
                    ft.Row(
                        [
                            btn_tab_usuarios,
                            btn_tab_maestra,
                            ft.IconButton(icon=ft.Icons.SYNC_ROUNDED, icon_color=ACCENT_CYAN, tooltip="Sincronizar Usuarios y Maestra", on_click=recargar_todo_admin_maestra),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                wrap=True,
            ),
        )

        col_principal = ft.Column([barra_titulo, contenedor_subvista], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

        self.vista = ft.Container(padding=14, bgcolor=BG_MODULO, content=col_principal, expand=True)
        self.cargar_maestra_skus_func = recargar_todo_admin_maestra
        self.cambiar_subvista_admin_func = cambiar_subvista_admin

    def cargar_maestra_skus(self, e=None):
        threading.Thread(target=self.cargar_maestra_skus_func, daemon=True).start()

    def sel_sub_maestra(self, idx: int):
        self.cambiar_subvista_admin_func(idx)
        threading.Thread(target=self.cargar_maestra_skus_func, daemon=True).start()