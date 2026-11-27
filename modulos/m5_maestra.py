import os
import json
import threading
from datetime import datetime
import pandas as pd
import flet as ft
from dependencias import *

RUTA_PERMISOS_LOCAL = "config_permisos_wms.cache.json"
RUTA_MAESTRA_EXTRA = "config_maestra_extra.cache.json"


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
            ("PC_RUTEO", "Ruteo y Facturación"),
            ("PC_IMPRESION", "Etiquetas & Impresión"),
            ("PC_CARGAS", "Cargas de camión (OT)"),
            ("PC_DESPACHOS", "Despachos de exportación"),
            ("PC_RECEPCION_CCP", "Recepción Traslados Concepción"),
        ]

        MODULOS_RF_LISTA = [
            ("RF_RECEPCION", "RF Recepción Andén"),
            ("RF_PUTAWAY", "RF Putaway (Ubicación)"),
            ("RF_PICKING", "RF Picking de Olas"),
            ("RF_REABASTECIMIENTO", "RF Reabastecimiento N1"),
            ("RF_INVENTARIO", "RF Auditoría & Conteo Cíclico"),
            ("RF_CONSULTA", "RF Consultor de Stock/LPN"),
        ]
        # Permisos antiguos del celular -> equivalentes nuevos (se llena desde Supabase)
        REEMPLAZA_RF = {}

        # Catálogo de módulos en Supabase (script 31): cada módulo nuevo aparece solo aquí
        try:
            _cat = (supabase.table("wms_modulos_app").select("codigo, plataforma, nombre, orden, reemplaza, activo")
                    .eq("activo", True).order("orden").execute().data or [])
            _rf = [(c["codigo"], c["nombre"]) for c in _cat if c.get("plataforma") == "RF"]
            _pc = [(c["codigo"], c["nombre"]) for c in _cat if c.get("plataforma") == "PC"]
            if _rf:
                MODULOS_RF_LISTA = _rf
                REEMPLAZA_RF = {c["codigo"]: set(c.get("reemplaza") or []) for c in _cat if c.get("plataforma") == "RF"}
            if _pc:
                MODULOS_PC_LISTA = _pc
        except Exception as _ex_cat:
            print(f"[WARN] Catálogo de módulos (ejecute 31_catalogo_modulos.sql): {_ex_cat}")

        # Perfiles de usuario (script 69): rol + módulos precargados al crear un usuario
        PERFILES_RESPALDO = [
            {"codigo": "ADMINISTRADOR", "nombre": "Administrador", "rol": "ADMIN",
             "modulos_pc": [c for c, _ in MODULOS_PC_LISTA if c != "PC_DESARROLLADOR"], "modulos_rf": [c for c, _ in MODULOS_RF_LISTA]},
            {"codigo": "SUPERVISOR", "nombre": "Supervisor de bodega", "rol": "SUPERVISOR",
             "modulos_pc": [c for c, _ in MODULOS_PC_LISTA if c not in ("PC_DESARROLLADOR", "PC_ADMIN_MAESTRA")],
             "modulos_rf": [c for c, _ in MODULOS_RF_LISTA]},
            {"codigo": "OPERADOR_RF", "nombre": "Operador celular (todo el celular)", "rol": "OPERADOR RF",
             "modulos_pc": [], "modulos_rf": [c for c, _ in MODULOS_RF_LISTA]},
        ]
        perfiles_db = []

        def cargar_perfiles():
            nonlocal perfiles_db
            try:
                perfiles_db = (supabase.table("wms_perfiles_usuario").select("*").eq("activo", True)
                               .order("orden").execute().data or [])
            except Exception as ex_pf:
                print(f"[WARN] Perfiles de usuario (ejecute 69_perfiles_usuario.sql): {ex_pf}")
                perfiles_db = []
            if not perfiles_db:
                perfiles_db = list(PERFILES_RESPALDO)

        cargar_perfiles()

        # --- 3. VARIABLES DE ESTADO ---
        lock_datos = threading.Lock()
        usuarios_db = []
        skus_db = []
        columnas_reales_maestra = set()
        columnas_reales_usuarios = set()
        id_usuario_editando = None
        sku_original_editando = None
        fila_original_editando = None     # fila de maestra_sku que se edita (sku + código de barras + unidad)
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
                opt_w("ADMIN OPERACIONES", "JEFE DE OPERACIONES (Admin.)"),
                opt_w("SUPERVISOR", "SUPERVISOR BODEGA"),
                opt_w("OPERADOR RF", "OPERADOR RF (Piso)"),
                opt_w("AUDITOR", "AUDITOR INVENTARIO"),
                opt_w("CONSULTA", "SOLO CONSULTA"),
            ],
        )
        dd_usr_perfil = dropdown_dark(
            label="Perfil (precarga rol y módulos)", width=300, value=None,
            options=[opt_w(str(pf.get("codigo")), str(pf.get("nombre") or pf.get("codigo"))) for pf in perfiles_db],
        )
        dd_usr_perfil_extra = dropdown_dark(
            label="Sumar otro perfil", width=250, value=None,
            options=[opt_w(str(pf.get("codigo")), str(pf.get("nombre") or pf.get("codigo"))) for pf in perfiles_db],
        )
        perfiles_elegidos = []          # códigos de perfil del usuario en el formulario (1 o más)
        lbl_perfil_desc = ft.Text("Elija un perfil: se marcan solos el rol y los módulos (puede ajustarlos antes de guardar).",
                                  size=11, color=TEXT_MUTED, italic=True)
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

        def _perfil(codigo: str) -> dict:
            return next((pf for pf in perfiles_db if str(pf.get("codigo")) == str(codigo or "")), {})

        def _nivel_rol(rol: str) -> int:
            r = str(rol or "").upper()
            if r == "ADMIN":
                return 6
            if "ADMIN" in r:
                return 5
            if "SUPERV" in r:
                return 4
            if "AUDITOR" in r:
                return 3
            if "OPERADOR" in r:
                return 2
            return 1

        def _fijar_rol(rol_pf: str):
            rol_pf = str(rol_pf or "OPERADOR RF").strip().upper()
            if rol_pf not in [o.key for o in dd_usr_rol.options]:
                dd_usr_rol.options.append(opt_w(rol_pf, rol_pf))
            dd_usr_rol.value = rol_pf

        def _describir_perfiles():
            nombres = [str(_perfil(c).get("nombre") or c) for c in perfiles_elegidos]
            n_pc = sum(1 for chk in checks_pc.values() if chk.value)
            n_rf = sum(1 for chk in checks_rf.values() if chk.value)
            lbl_perfil_desc.value = (" + ".join(nombres) + f" · rol {dd_usr_rol.value} · {n_pc} módulos PC · "
                                     f"{n_rf} módulos celular. Puede ajustarlos antes de guardar.") if nombres else \
                "Elija un perfil: se marcan solos el rol y los módulos (puede ajustarlos antes de guardar)."

        def aplicar_perfil(e=None, actualizar: bool = True):
            """Perfil principal: reemplaza rol y módulos por los del perfil."""
            pf = _perfil(dd_usr_perfil.value)
            if not pf:
                return
            perfiles_elegidos[:] = [str(pf.get("codigo"))]
            pc_pf = {str(x).upper() for x in (pf.get("modulos_pc") or [])}
            rf_pf = {str(x).upper() for x in (pf.get("modulos_rf") or [])}
            for k, chk in checks_pc.items():
                chk.value = k in pc_pf
            for k, chk in checks_rf.items():
                chk.value = k in rf_pf
            _fijar_rol(pf.get("rol"))
            _describir_perfiles()
            if actualizar:
                page.update()

        def sumar_perfil(e=None):
            """Suma los módulos de otro perfil sin desmarcar los que ya tiene; queda el rol más alto."""
            pf = _perfil(dd_usr_perfil_extra.value)
            dd_usr_perfil_extra.value = None
            if not pf:
                page.update()
                return
            if not perfiles_elegidos:
                dd_usr_perfil.value = pf.get("codigo")
                aplicar_perfil()
                return
            if str(pf.get("codigo")) not in perfiles_elegidos:
                perfiles_elegidos.append(str(pf.get("codigo")))
            for k in pf.get("modulos_pc") or []:
                if str(k).upper() in checks_pc:
                    checks_pc[str(k).upper()].value = True
            for k in pf.get("modulos_rf") or []:
                if str(k).upper() in checks_rf:
                    checks_rf[str(k).upper()].value = True
            if _nivel_rol(pf.get("rol")) > _nivel_rol(dd_usr_rol.value):
                _fijar_rol(pf.get("rol"))
            _describir_perfiles()
            page.update()

        for _dd, _fn in ((dd_usr_perfil, aplicar_perfil), (dd_usr_perfil_extra, sumar_perfil)):
            _dd.on_change = _fn
            try:
                _dd.on_select = _fn      # Flet nuevo: el Dropdown avisa con on_select
            except Exception:
                pass

        def guardar_modulos_en_perfil(e=None):
            pf = _perfil(dd_usr_perfil.value)
            if not pf:
                notificar("Elija primero el perfil que quiere actualizar.", "#D97706")
                return
            if len(perfiles_elegidos) > 1:
                notificar("Hay perfiles sumados: deje un solo perfil para guardar sus módulos.", "#D97706")
                return
            pc_sel = [k for k, chk in checks_pc.items() if chk.value and k != "PC_DESARROLLADOR"]
            rf_sel = [k for k, chk in checks_rf.items() if chk.value]
            datos_pf = {"modulos_pc": pc_sel, "modulos_rf": rf_sel, "rol": (dd_usr_rol.value or pf.get("rol")),
                        "actualizado_en": datetime.now().isoformat(),
                        "actualizado_por": str(getattr(page, "usuario_actual", "") or "")}
            try:
                supabase.table("wms_perfiles_usuario").update(datos_pf).eq("codigo", pf["codigo"]).execute()
            except Exception as ex_pf:
                notificar(f"No se pudo guardar el perfil (¿ejecutó el script 69?): {ex_pf}", "#B91C1C")
                return
            cargar_perfiles()
            notificar(f"Perfil «{pf.get('nombre')}» actualizado: {len(pc_sel)} módulos PC y {len(rf_sel)} de celular. "
                      "Los usuarios ya creados no cambian.", "#047857")

        def permisos_rf_vigentes(rf_lista: list) -> list:
            """Si el usuario todavía tiene permisos antiguos (RF_PICKING, RF_INVENTARIO...), se muestran como
            los módulos nuevos equivalentes. Al guardar quedan solo los nuevos."""
            codigos = {k for k, _ in MODULOS_RF_LISTA}
            if not REEMPLAZA_RF:
                return rf_lista
            if any(str(x).startswith("APP_") for x in rf_lista):
                return [x for x in rf_lista if x in codigos]
            antiguos = set(rf_lista)
            return [k for k in codigos if REEMPLAZA_RF.get(k, set()) & antiguos]

        def obtener_permisos_usuario(row_u: dict) -> tuple:
            u_key = str(row_u.get("usuario") or "").strip().upper()
            rol_u = str(row_u.get("rol") or "").strip().upper()
            mapa_local = leer_json_local(RUTA_PERMISOS_LOCAL)

            pc_raw = row_u.get("modulos_pc") or row_u.get("permisos_pc")
            rf_raw = row_u.get("modulos_rf") or row_u.get("permisos_rf")

            if pc_raw is not None or rf_raw is not None:
                # En Supabase son columnas text[] (llegan como lista)
                return (lista_permisos(pc_raw), permisos_rf_vigentes(lista_permisos(rf_raw)))

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
            dd_usr_perfil.value = None
            dd_usr_perfil_extra.value = None
            perfiles_elegidos.clear()
            lbl_perfil_desc.value = "Elija un perfil: se marcan solos el rol y los módulos (puede ajustarlos antes de guardar)."
            for c in checks_pc.values(): c.value = False
            for c in checks_rf.values(): c.value = False
            page.update()

        def cargar_usuario_en_formulario(row_u: dict):
            nonlocal id_usuario_editando
            id_usuario_editando = row_u.get("id")
            u_log = str(row_u.get("usuario") or "").strip()
            lbl_modo_form_usr.value = f"MODO: EDITANDO USUARIO [{u_log}]"
            lbl_modo_form_usr.color = ACCENT_AMBER
            txt_usr_login.value = u_log
            txt_usr_nombre.value = str(row_u.get("nombre_completo") or "")
            # La contraseña no se muestra (puede estar cifrada): en blanco = se mantiene la actual
            txt_usr_pass.value = ""
            txt_usr_pass.hint_text = "(sin cambios)"
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
            codigos_u = [c.strip() for c in str(row_u.get("perfil") or "").split("+") if _perfil(c.strip())]
            perfiles_elegidos[:] = codigos_u
            dd_usr_perfil.value = codigos_u[0] if codigos_u else None
            dd_usr_perfil_extra.value = None
            lbl_perfil_desc.value = ("Perfil: " + " + ".join(str(_perfil(c).get("nombre")) for c in codigos_u)
                                     + ". Los módulos son los guardados del usuario.") if codigos_u else \
                "Usuario sin perfil asignado: puede elegir uno para precargar módulos."

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

            if not u_log or not u_nom or (not u_pass and id_usuario_editando is None):
                notificar("Complete Usuario, Nombre Completo y Contraseña.", "#D97706")
                return

            pc_sel = [k for k, chk in checks_pc.items() if chk.value]
            rf_sel = [k for k, chk in checks_rf.items() if chk.value]
            if not pc_sel and not rf_sel and "ADMIN" not in u_rol.upper():
                notificar("Elija un perfil o marque al menos un módulo.", "#D97706")
                return
            # Compatibilidad: los celulares con la app anterior solo entienden los permisos antiguos
            # (RF_...). Se guardan junto a los nuevos; la app nueva usa solo los APP_ e ignora estos.
            LEGADO_RF = {
                "APP_RECEPCION": "RF_RECEPCION", "APP_MAESTRA": "RF_RECEPCION", "APP_TRASLADOS": "RF_TRASLADOS",
                "APP_ALMACENAMIENTO": "RF_PUTAWAY", "APP_REABASTECIMIENTO": "RF_REABASTECIMIENTO",
                "APP_PICKING": "RF_PICKING", "APP_PICKING_FARMACIA": "RF_PICKING", "APP_PACKING": "RF_PICKING",
                "APP_STOCK_CONTEO": "RF_CONSULTA", "APP_VACIAS": "RF_INVENTARIO", "APP_CICLICO_SKU": "RF_INVENTARIO",
                "APP_PICKING_OT": "RF_PICKING", "APP_CARGA_CAMION": "RF_PICKING",
                "APP_DESPACHO_EXPORT": "RF_PICKING",
            }
            if any(k.startswith("APP_") for k in rf_sel):
                rf_sel = rf_sel + sorted({LEGADO_RF[k] for k in rf_sel if k in LEGADO_RF} - set(rf_sel))

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
            if not u_pass:
                payload_base.pop("password", None)  # editar sin cambiar la contraseña
            payload_ext = dict(payload_base)
            # Columnas text[] en Supabase: se envían como lista (antes el texto "A,B" fallaba en silencio)
            payload_ext["modulos_pc"] = pc_sel
            payload_ext["modulos_rf"] = rf_sel
            if perfiles_elegidos and (not columnas_reales_usuarios or "perfil" in columnas_reales_usuarios):
                payload_ext["perfil"] = "+".join(perfiles_elegidos)

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
        dd_sku_um = dropdown_dark(
            label="Unidad de medida", width=150, value="CAJA",
            options=[opt_w("UNIDAD", "UNIDAD"), opt_w("DISPLAY", "DISPLAY"), opt_w("CAJA", "CAJA")],
        )
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
            nonlocal sku_original_editando, fila_original_editando
            sku_original_editando = info_s["sku"]
            raw = info_s.get("raw") or {}
            fila_original_editando = {"sku": raw.get("sku"), "codigo_barras": raw.get("codigo_barras"),
                                      "unidad_medida": raw.get("unidad_medida")}
            um = str(raw.get("unidad_medida") or "").strip().upper()
            if um:
                if um not in [o.key for o in dd_sku_um.options]:
                    dd_sku_um.options.append(opt_w(um, um))
                dd_sku_um.value = um
            else:
                dd_sku_um.value = "UNIDAD" if int(float(info_s.get("multiplo") or 1)) <= 1 else "CAJA"
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
            nonlocal sku_original_editando, fila_original_editando
            sku_original_editando = None
            fila_original_editando = None
            dd_sku_um.value = "CAJA"
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

            if filtro and not nuevas_filas and not getattr(renderizar_tabla_maestra, "_buscando", False):
                renderizar_tabla_maestra._buscando = True
                try:
                    if buscar_sku_en_servidor(filtro):
                        return renderizar_tabla_maestra()
                finally:
                    renderizar_tabla_maestra._buscando = False
            tabla_maestra_skus.rows = nuevas_filas
            lbl_kpi_sku_total.value = str(len(copia_skus))
            lbl_kpi_sku_farma.value = str(farma_cnt)
            lbl_kpi_sku_con_multiplo.value = str(mult_cnt)
            page.update()

        txt_buscar_sku.on_change = renderizar_tabla_maestra

        def cargar_maestra_skus(e=None):
            nonlocal skus_db, columnas_reales_maestra
            with lock_datos:
                # Todas las filas, ordenadas (sin orden la paginación puede saltarse o repetir SKU) y sin tope:
                # antes se cortaba si Supabase devolvía menos de 1.000 por página (límite "Max rows" del proyecto).
                try:
                    acumulado = leer_tabla_paginada(lambda: supabase.table("maestra_sku").select("*").order("sku"))
                except Exception as ex:
                    acumulado = None
                    notificar(f"No se pudo leer la maestra completa: {getattr(ex, 'message', None) or ex}", "#B91C1C")
                if acumulado is not None:
                    skus_db = acumulado
                if skus_db:
                    columnas_reales_maestra = set(skus_db[0].keys())
            renderizar_tabla_maestra()

        def buscar_sku_en_servidor(filtro: str) -> bool:
            """Si lo buscado no está en lo cargado, se busca directo en maestra_sku (SKU, descripción o código)."""
            nonlocal skus_db
            limpio = "".join(c for c in filtro if c.isalnum() or c in "-_ .")
            if len(limpio) < 3:
                return False
            try:
                res = (supabase.table("maestra_sku").select("*")
                       .or_(f"sku.ilike.*{limpio}*,descripcion.ilike.*{limpio}*,codigo_barras.ilike.*{limpio}*")
                       .limit(300).execute().data or [])
            except Exception:
                return False
            conocidos = {str(x.get("sku") or "").strip().upper() for x in skus_db}
            nuevos = [x for x in res if str(x.get("sku") or "").strip().upper() not in conocidos]
            if nuevos:
                skus_db = list(skus_db) + nuevos
            return bool(nuevos)

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

            # Un SKU tiene varias filas en maestra_sku (UNIDAD / DISPLAY / CAJA): la fila se identifica por
            # SKU + código de barras + unidad de medida. Se actualiza la fila editada o se crea una nueva.
            payload_supa["unidad_medida"] = (dd_sku_um.value or ("UNIDAD" if mult_val <= 1 else "CAJA")).strip().upper()

            def _filtrar(q, fila):
                q = q.eq("sku", fila.get("sku")).eq("codigo_barras", fila.get("codigo_barras"))
                um = fila.get("unidad_medida")
                return q.eq("unidad_medida", um) if um not in (None, "") else q.is_("unidad_medida", "null")

            guardado_ok = False
            try:
                filas_act = []
                original = fila_original_editando if sku_original_editando else None
                if original and original.get("sku"):
                    filas_act = _filtrar(supabase.table("maestra_sku").update(payload_supa), original).execute().data or []
                if not filas_act:
                    misma = {"sku": sku_c, "codigo_barras": payload_supa["codigo_barras"], "unidad_medida": payload_supa["unidad_medida"]}
                    filas_act = _filtrar(supabase.table("maestra_sku").update(payload_supa), misma).execute().data or []
                if not filas_act:
                    supabase.table("maestra_sku").insert(payload_supa).execute()
                guardado_ok = True
            except Exception as ex_up:
                msg_up = str(getattr(ex_up, "message", None) or ex_up)
                if "duplicate key" in msg_up or "23505" in msg_up:
                    msg_up = ("ya existe otra fila con ese SKU, código de barras y unidad de medida. "
                              "Edite esa fila o cambie el código de barras / la unidad.")
                notificar(f"Error guardando en Supabase: {msg_up}", "#B91C1C")
                return

            if guardado_ok:
                notificar(f"Ficha Maestra de SKU [{sku_c}] guardada y sincronizada.", "#047857")
                limpiar_formulario_sku()
                cargar_maestra_skus()

        def abrir_traer_netsuite(e=None):
            """Busca artículos en NetSuite y crea en la maestra los que faltan (UNIDAD + CAJA de compra)."""
            try:
                from conexion_erp import consultar_netsuite
                from servicios.maestra_netsuite import buscar_items_netsuite, crear_en_maestra, skus_que_faltan
            except Exception as ex_imp:
                notificar(f"La conexión con NetSuite no está disponible: {ex_imp}", "#D97706")
                return
            txt_buscar_ns = ft.TextField(label="Código, nombre o código de barras en NetSuite", dense=True, width=360,
                                         color=TEXT_WHITE, bgcolor=BG_INPUT, border_color=BORDER_COLOR,
                                         text_style=ft.TextStyle(size=12))
            lbl_ns = ft.Text("", size=11.5, color=TEXT_MUTED)
            lista_ns = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, height=330)
            items_ns, checks_ns = [], {}

            def pintar(items, faltan):
                items_ns[:] = items
                checks_ns.clear()
                filas = []
                for it in items:
                    nuevo = it["sku"] in faltan
                    chk = ft.Checkbox(value=nuevo, disabled=not nuevo)
                    checks_ns[it["sku"]] = chk
                    filas.append(ft.Row([
                        chk,
                        ft.Text(it["sku"], size=11.5, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN, width=120),
                        ft.Text(str(it["descripcion"])[:42], size=11.5, color=TEXT_WHITE, width=300),
                        ft.Text(f"UPC {it.get('upc') or '-'}", size=11, color=TEXT_MUTED, width=140),
                        ft.Text(f"{it.get('unidad_compra') or 'UN'} x{it.get('factor_compra') or 1}", size=11, color=ACCENT_GREEN, width=110),
                        ft.Text("nuevo" if nuevo else "ya está en la maestra", size=11, color="#FBBF24" if nuevo else TEXT_MUTED),
                    ], spacing=8))
                lista_ns.controls = filas or [ft.Text("Sin resultados en NetSuite.", size=12, color=TEXT_MUTED)]
                lbl_ns.value = f"{len(items)} artículos · {sum(1 for i in items if i['sku'] in faltan)} no están en la maestra"
                page.update()

            def buscar(ev=None):
                t = (txt_buscar_ns.value or "").strip()
                if len(t) < 3:
                    notificar("Escriba al menos 3 caracteres.", "#D97706")
                    return
                lbl_ns.value = "Buscando en NetSuite..."
                page.update()
                try:
                    items = buscar_items_netsuite(consultar_netsuite, texto=t)
                    pintar(items, set(skus_que_faltan(supabase, [i["sku"] for i in items])))
                except Exception as ex_b:
                    lbl_ns.value = f"No se pudo buscar: {ex_b}"
                    page.update()

            def faltantes_oc(ev=None):
                lbl_ns.value = "Revisando los SKU de las OC abiertas..."
                page.update()
                try:
                    abiertas = [r["id"] for r in (supabase.table("asn_cabecera").select("id")
                                                  .eq("estado", "EN_RECEPCION").execute().data or [])]
                    skus = set()
                    for i in range(0, len(abiertas), 100):
                        skus |= {str(r.get("sku") or "").strip().upper() for r in (
                            supabase.table("asn_detalle").select("sku").in_("asn_id", abiertas[i:i + 100]).execute().data or [])}
                    faltan = skus_que_faltan(supabase, skus)
                    if not faltan:
                        lista_ns.controls = [ft.Text("Todos los SKU de las OC abiertas están en la maestra.", size=12, color=ACCENT_GREEN)]
                        lbl_ns.value = ""
                        page.update()
                        return
                    items = buscar_items_netsuite(consultar_netsuite, skus=faltan)
                    pintar(items, set(faltan))
                    sin = [s_ for s_ in faltan if s_ not in {i["sku"] for i in items}]
                    if sin:
                        lbl_ns.value += f" · sin ficha en NetSuite: {', '.join(sin[:6])}"
                        page.update()
                except Exception as ex_f:
                    lbl_ns.value = f"No se pudo revisar: {ex_f}"
                    page.update()

            def crear(ev=None):
                elegidos = [it for it in items_ns if checks_ns.get(it["sku"]) and checks_ns[it["sku"]].value]
                if not elegidos:
                    notificar("Marque los artículos a crear.", "#D97706")
                    return
                try:
                    n = crear_en_maestra(supabase, elegidos)
                except Exception as ex_c:
                    notificar(f"No se pudo crear en la maestra: {ex_c}", "#B91C1C")
                    return
                page.pop_dialog()
                notificar(f"{n} SKU creados en la maestra desde NetSuite.", "#047857")
                cargar_maestra_skus()

            page.show_dialog(ft.AlertDialog(
                bgcolor="#1E293B",
                title=ft.Text("Traer SKU desde NetSuite", size=16, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                content=ft.Container(width=880, content=ft.Column([
                    ft.Text("Crea en la maestra los artículos que faltan, con su nombre, código de barras (UPC) y la caja "
                            "de compra de NetSuite. Los SKU que ya están en la maestra no se modifican.", size=11.5, color=TEXT_MUTED),
                    ft.Row([txt_buscar_ns, boton_primario("BUSCAR", ft.Icons.SEARCH_ROUNDED, buscar, ACCENT_BLUE, height_val=32),
                            boton_primario("SKU DE OC SIN MAESTRA", ft.Icons.PLAYLIST_ADD_CHECK_ROUNDED, faltantes_oc, ACCENT_TEAL, height_val=32)],
                           spacing=8, wrap=True),
                    lbl_ns,
                    lista_ns,
                ], spacing=10, tight=True)),
                actions=[ft.TextButton("CERRAR", on_click=lambda ev: page.pop_dialog()),
                         boton_primario("CREAR EN MAESTRA", ft.Icons.ADD_TASK_ROUNDED, crear, "#047857", height_val=32)],
            ))
            page.update()

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
                                            dd_sku_um,
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
                                            boton_primario("TRAER SKU DE NETSUITE", ft.Icons.CLOUD_DOWNLOAD_OUTLINED, abrir_traer_netsuite, ACCENT_BLUE, height_val=32),
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
                                            dd_usr_perfil,
                                            dd_usr_perfil_extra,
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
                                            boton_primario("GUARDAR MÓDULOS EN EL PERFIL", ft.Icons.BOOKMARK_ADD_OUTLINED, guardar_modulos_en_perfil, ACCENT_PURPLE, height_val=30),
                                            lbl_perfil_desc,
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