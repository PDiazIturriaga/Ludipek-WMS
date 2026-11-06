import os
import math
import time
import shutil
import threading
import traceback
import flet as ft
from dependencias import *
from modulos import m0_dashboard, m1_recepcion, m2_putaway, m3_picking, m4_inventario, m5_maestra, m6_impresion


def dibujar_frame_gato_realista(phase: float, sitting: bool = False):
    from PIL import Image, ImageDraw, ImageFilter

    # Renderizado a 4x (440x260) con suavizado LANCZOS para lograr bordes e iluminación realistas
    W, H = 440, 260
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Sombra proyectada en el piso con desenfoque gaussiano
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    if not sitting:
        sdraw.ellipse([95, 218, 335, 242], fill=(15, 23, 42, 95))
    else:
        sdraw.ellipse([140, 218, 310, 242], fill=(15, 23, 42, 105))
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    img.alpha_composite(shadow)

    draw = ImageDraw.Draw(img)

    # Paleta realista (Gato Tuxedo / Gris Carbón Satinado con pecho y guantes blancos y ojos esmeralda)
    FUR_DARK = (38, 46, 56, 255)
    FUR_MID = (58, 69, 82, 255)
    FUR_LIGHT = (82, 96, 112, 255)
    FUR_SHADOW = (24, 30, 38, 255)
    WHITE_FUR = (248, 250, 252, 255)
    WHITE_SHADE = (218, 226, 235, 255)
    PINK_EAR = (232, 142, 160, 255)
    NOSE_PINK = (225, 115, 138, 255)
    EYE_GREEN = (52, 211, 153, 255)
    EYE_PUPIL = (15, 23, 42, 255)
    COLLAR_TEAL = (14, 165, 233, 255)
    GOLD_BELL = (250, 204, 21, 255)

    def draw_limb(joints, widths, color_main, paw_color=WHITE_FUR):
        for i in range(len(joints) - 1):
            x0, y0 = joints[i]
            x1, y1 = joints[i + 1]
            r0, r1 = widths[i], widths[i + 1]
            dx, dy = x1 - x0, y1 - y0
            dist = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / dist, dx / dist
            poly = [
                (x0 + nx * r0, y0 + ny * r0),
                (x1 + nx * r1, y1 + ny * r1),
                (x1 - nx * r1, y1 - ny * r1),
                (x0 - nx * r0, y0 - ny * r0),
            ]
            draw.polygon(poly, fill=color_main)
            draw.ellipse([x0 - r0, y0 - r0, x0 + r0, y0 + r0], fill=color_main)
            draw.ellipse([x1 - r1, y1 - r1, x1 + r1, y1 + r1], fill=color_main)
        px, py = joints[-1]
        pw, ph = widths[-1] * 1.35, widths[-1] * 0.95
        draw.ellipse([px - pw * 0.7, py - ph, px + pw * 1.4, py + ph], fill=paw_color)

    if not sitting:
        bob = math.sin(phase * 2) * 4.0

        def leg_kinematics(hip_x, hip_y, angle_offset, is_front=False):
            a = phase + angle_offset
            stride = math.sin(a)
            lift = max(0.0, -math.cos(a))
            foot_x = hip_x + stride * (34 if is_front else 36)
            foot_y = 224 - lift * 26
            if is_front:
                mid_x = (hip_x + foot_x) * 0.5 - 8 + stride * 6
                mid_y = (hip_y + foot_y) * 0.5 - lift * 10
            else:
                mid_x = (hip_x + foot_x) * 0.5 - 14 + stride * 8
                mid_y = (hip_y + foot_y) * 0.5 + 4 - lift * 8
            return [(hip_x, hip_y), (mid_x, mid_y), (foot_x, foot_y)]

        # Patas en segundo plano (sombreadas para dar profundidad 3D)
        draw_limb(leg_kinematics(138, 138 + bob, math.pi, False), [20, 13, 9], FUR_SHADOW, WHITE_SHADE)
        draw_limb(leg_kinematics(272, 142 + bob, math.pi * 1.5, True), [18, 12, 8.5], FUR_SHADOW, WHITE_SHADE)

        # Cola con curva en S dinámica
        tail_pts = []
        for t_i in range(25):
            t = t_i / 24.0
            tx = 118 - t * 88
            ty = 118 + bob - math.sin(t * math.pi * 0.85) * 58 + math.sin(phase + t * 2.5) * 10
            tail_pts.append((tx, ty))
        for i in range(len(tail_pts) - 1):
            r = 12 * (1 - i / 32.0)
            x0, y0 = tail_pts[i]
            x1, y1 = tail_pts[i + 1]
            draw.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=FUR_DARK)
            draw.line([x0, y0, x1, y1], fill=FUR_DARK, width=int(r * 2))

        # Torso anatómico felino con brillo dorsal y pecho blanco
        draw.ellipse([105, 92 + bob, 215, 172 + bob], fill=FUR_DARK)
        draw.ellipse([215, 96 + bob, 312, 178 + bob], fill=FUR_DARK)
        draw.polygon([(155, 93 + bob), (275, 97 + bob), (285, 174 + bob), (145, 168 + bob)], fill=FUR_DARK)
        draw.pieslice([235, 108 + bob, 316, 178 + bob], start=-45, end=75, fill=WHITE_FUR)
        draw.chord([125, 94 + bob, 290, 145 + bob], start=185, end=355, fill=FUR_MID)
        draw.chord([145, 96 + bob, 270, 128 + bob], start=190, end=350, fill=FUR_LIGHT)

        # Patas en primer plano
        draw_limb(leg_kinematics(144, 138 + bob, 0.0, False), [22, 14, 9.5], FUR_DARK, WHITE_FUR)
        draw_limb(leg_kinematics(278, 142 + bob, math.pi * 0.5, True), [19, 12.5, 9], FUR_DARK, WHITE_FUR)

        head_cx, head_cy = 315, 92 + bob * 0.7
    else:
        # Pose sentada elegante cuando se detiene a saludar
        draw.arc([95, 185, 235, 236], start=110, end=290, fill=FUR_DARK, width=22)
        draw.ellipse([145, 118, 255, 226], fill=FUR_DARK)
        draw.polygon([(175, 130), (265, 95), (295, 175), (215, 224)], fill=FUR_DARK)
        draw.ellipse([210, 92, 305, 188], fill=FUR_DARK)
        draw.ellipse([242, 112, 306, 185], fill=WHITE_FUR)
        draw_limb([(255, 150), (262, 190), (268, 224)], [17, 12, 9], FUR_SHADOW, WHITE_SHADE)
        draw_limb([(274, 152), (282, 192), (288, 224)], [18, 13, 9.5], FUR_DARK, WHITE_FUR)
        head_cx, head_cy = 292, 78

    # Collar corporativo Ludipek + cascabel dorado
    draw.polygon(
        [(head_cx - 32, head_cy + 22), (head_cx + 12, head_cy + 36), (head_cx + 6, head_cy + 46), (head_cx - 38, head_cy + 31)],
        fill=COLLAR_TEAL,
    )
    bx, by = head_cx + 8, head_cy + 44
    draw.ellipse([bx - 8, by - 8, bx + 8, by + 8], fill=GOLD_BELL, outline=(161, 98, 7, 255), width=2)

    # Cabeza, orejas perfiladas, hocico blanco, nariz, ojos esmeralda con reflejo y bigotes
    draw.polygon([(head_cx + 2, head_cy - 28), (head_cx + 24, head_cy - 62), (head_cx + 34, head_cy - 20)], fill=FUR_SHADOW)
    draw.polygon([(head_cx + 8, head_cy - 28), (head_cx + 22, head_cy - 54), (head_cx + 29, head_cy - 22)], fill=PINK_EAR)

    draw.ellipse([head_cx - 38, head_cy - 36, head_cx + 42, head_cy + 34], fill=FUR_DARK)
    draw.chord([head_cx - 30, head_cy - 34, head_cx + 34, head_cy + 10], start=190, end=340, fill=FUR_MID)

    draw.polygon([(head_cx - 26, head_cy - 22), (head_cx - 8, head_cy - 64), (head_cx + 14, head_cy - 26)], fill=FUR_DARK)
    draw.polygon([(head_cx - 19, head_cy - 24), (head_cx - 6, head_cy - 54), (head_cx + 8, head_cy - 27)], fill=PINK_EAR)

    draw.ellipse([head_cx + 4, head_cy - 2, head_cx + 48, head_cy + 28], fill=WHITE_FUR)
    draw.ellipse([head_cx - 8, head_cy + 6, head_cx + 36, head_cy + 32], fill=WHITE_FUR)

    nx, ny = head_cx + 42, head_cy + 6
    draw.polygon([(nx - 6, ny - 4), (nx + 5, ny - 3), (nx, ny + 5)], fill=NOSE_PINK)

    ex, ey = head_cx + 18, head_cy - 6
    draw.ellipse([ex - 9, ey - 8, ex + 9, ey + 8], fill=EYE_GREEN, outline=FUR_SHADOW, width=2)
    draw.ellipse([ex - 3, ey - 6, ex + 3, ey + 6], fill=EYE_PUPIL)
    draw.ellipse([ex + 1, ey - 5, ex + 5, ey - 1], fill=(255, 255, 255, 240))

    for wy_off, wx_end, wy_end in [(12, 65, 6), (16, 68, 16), (20, 62, 26)]:
        draw.line([head_cx + 26, head_cy + wy_off, head_cx + wx_end, head_cy + wy_end], fill=(241, 245, 249, 210), width=2)

    return img.resize((125, 74), Image.Resampling.LANCZOS)


def preparar_assets_visuales():
    from PIL import Image
    os.makedirs("assets", exist_ok=True)
    os.makedirs(os.path.join("assets", "icons"), exist_ok=True)

    ruta_logo_assets = os.path.join("assets", "logo.png")
    if not os.path.exists(ruta_logo_assets) and os.path.exists("logo.png"):
        try:
            shutil.copyfile("logo.png", ruta_logo_assets)
        except Exception:
            pass

    # Generar automáticamente Favicon y Pantalla de Carga Web desde logo.png
    if os.path.exists(ruta_logo_assets):
        try:
            with Image.open(ruta_logo_assets).convert("RGBA") as im_logo:
                # 1. Icono de la pestaña del navegador (Favicon)
                im_logo.resize((64, 64), Image.Resampling.LANCZOS).save(
                    os.path.join("assets", "favicon.png"), format="PNG"
                )
                # 2. Icono de carga al abrir la página (Splash screen)
                im_logo.resize((180, 180), Image.Resampling.LANCZOS).save(
                    os.path.join("assets", "icons", "loading-animation.png"), format="PNG"
                )
                # 3. Iconos para accesos directos en PC y móviles (PWA)
                im_logo.resize((192, 192), Image.Resampling.LANCZOS).save(
                    os.path.join("assets", "icons", "Icon-192.png"), format="PNG"
                )
                im_logo.resize((512, 512), Image.Resampling.LANCZOS).save(
                    os.path.join("assets", "icons", "Icon-512.png"), format="PNG"
                )
                im_logo.resize((180, 180), Image.Resampling.LANCZOS).save(
                    os.path.join("assets", "apple-touch-icon.png"), format="PNG"
                )
        except Exception as ex_ico:
            print(f"[WARN] No se pudieron generar los iconos web: {ex_ico}")

    # Sprites del gato guardián
    try:
        for idx_f in range(6):
            ruta_f = os.path.join("assets", f"cat_walk_{idx_f}.png")
            if not os.path.exists(ruta_f):
                im_f = dibujar_frame_gato_realista(phase=(idx_f / 6.0) * 2 * math.pi, sitting=False)
                im_f.save(ruta_f, format="PNG")
        ruta_sit = os.path.join("assets", "cat_sit.png")
        if not os.path.exists(ruta_sit):
            im_s = dibujar_frame_gato_realista(phase=0.0, sitting=True)
            im_s.save(ruta_sit, format="PNG")
    except Exception as ex_cat:
        print(f"[WARN] No se pudieron generar los sprites realistas del gato: {ex_cat}")


preparar_assets_visuales()


def main(page: ft.Page):
    page.title = "LUDIPEK WMS | Cloud Planning"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.window.maximized = True
    page.overlay.clear()

    # PANTALLA DE LOGIN INICIAL
    txt_login_user = ft.TextField(label="Usuario / RUT", width=300, prefix_icon=ft.Icons.PERSON)
    txt_login_pass = ft.TextField(label="Contraseña", width=300, password=True, can_reveal_password=True, prefix_icon=ft.Icons.LOCK)
    lbl_login_error = ft.Text("", color="#B91C1C", size=12, weight=ft.FontWeight.BOLD)

    def mostrar_pantalla_login():
        page.controls.clear()
        page.overlay.clear()
        page.bgcolor = "#292526"
        txt_login_pass.value = ""
        lbl_login_error.value = ""
        page.add(pantalla_login)
        page.update()

    intentos_fallidos = 0
    bloqueado_hasta = 0.0

    def intentar_login(e=None):
        nonlocal intentos_fallidos, bloqueado_hasta
        ahora = time.time()
        if ahora < bloqueado_hasta:
            seg_rest = int(bloqueado_hasta - ahora)
            lbl_login_error.value = f"Demasiados intentos. Espere {seg_rest}s."
            page.update()
            return

        user_val = (txt_login_user.value or "").strip().upper()
        pass_val = (txt_login_pass.value or "").strip()
        if not user_val or not pass_val:
            lbl_login_error.value = "Ingrese usuario y contraseña."
            page.update()
            return
        try:
            res = supabase.table("wms_usuarios").select("*").ilike("usuario", user_val).limit(1).execute()
            fila_u = res.data[0] if res.data else None

            if fila_u and fila_u.get("activo") and verificar_password_seguro(pass_val, fila_u.get("password", "")):
                intentos_fallidos = 0
                # Si la contraseña aún estaba en texto plano, encriptarla automáticamente en Supabase
                if not str(fila_u.get("password", "")).startswith("sha256$"):
                    try:
                        supabase.table("wms_usuarios").update({"password": hash_password_seguro(pass_val)}).eq("id", fila_u["id"]).execute()
                    except Exception:
                        pass

                page.usuario_actual = fila_u.get("nombre_completo") or user_val
                page.rol_actual = str(fila_u.get("rol") or "OPERADOR").upper()
                page.modulos_pc_usuario = str(fila_u.get("modulos_pc") or "")
                iniciar_torre_de_control()
            else:
                intentos_fallidos += 1
                if intentos_fallidos >= 5:
                    bloqueado_hasta = time.time() + 60
                    lbl_login_error.value = "Cuenta bloqueada temporalmente por 60 segundos."
                else:
                    lbl_login_error.value = f"Credenciales incorrectas o usuario inactivo ({intentos_fallidos}/5)."
                page.update()
        except Exception as ex:
            traceback.print_exc()
            lbl_login_error.value = f"Error al iniciar: {ex}"
            page.update()

    pantalla_login = ft.Container(
        expand=True, alignment=ft.Alignment.CENTER, bgcolor="#292526",
        content=ft.Container(
            padding=40, width=400, bgcolor=ft.Colors.WHITE, border_radius=16,
            shadow=ft.BoxShadow(blur_radius=30, color="#73000000", spread_radius=5, offset=ft.Offset(0, 10)),
            content=ft.Column([
                ft.Icon(ft.Icons.ACCOUNT_CIRCLE_ROUNDED, size=80, color="#507572"),
                ft.Text("INICIAR SESIÓN", size=24, weight=ft.FontWeight.W_900, color="#273132"),
                ft.Text("LUDIPEK WMS CLOUD", size=12, color="#64748B", weight=ft.FontWeight.BOLD),
                ft.Divider(height=25, color="transparent"),
                txt_login_user, txt_login_pass, lbl_login_error,
                ft.Divider(height=15, color="transparent"),
                ft.Button(
                    content=ft.Text("INGRESAR A WMS", weight=ft.FontWeight.BOLD),
                    bgcolor="#507572", color=ft.Colors.WHITE, width=300, height=48,
                    on_click=intentar_login,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))
                )
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True, spacing=10)
        )
    )

    page.bgcolor = "#292526"
    page.add(pantalla_login)

    def iniciar_torre_de_control():
        tarjetas_adaptables = []
        kpis_adaptables = []
        indice_modulo_activo = -1
        sesion_activa = True
        historial_recientes = []

        def get_indice_activo():
            return indice_modulo_activo

        def wrapper_activar(mod, sub=0):
            activar_modulo_principal(mod, sub)

        dash = m0_dashboard.DashboardModulo(page, tarjetas_adaptables, kpis_adaptables, wrapper_activar)
        recep = m1_recepcion.RecepcionModulo(page, tarjetas_adaptables, kpis_adaptables, get_indice_activo)
        puta = m2_putaway.PutawayModulo(page, tarjetas_adaptables, kpis_adaptables)
        pick = m3_picking.PickingModulo(page, tarjetas_adaptables, kpis_adaptables)
        inv = m4_inventario.InventarioModulo(page, tarjetas_adaptables, kpis_adaptables)
        mae = m5_maestra.MaestraModulo(page, tarjetas_adaptables, kpis_adaptables)
        imp = m6_impresion.ImpresionModulo(page, tarjetas_adaptables, kpis_adaptables)

        vistas_mapa = [
            ("Dashboards", ft.Icons.MONITOR_HEART_OUTLINED, dash.vista, dash.refrescar_dashboard, dash.sel_sub_dash, [("1. Vista Integral (BI + POs)", ft.Icons.DASHBOARD_OUTLINED), ("2. Productividad & Dock-to-Stock", ft.Icons.BOLT_ROUNDED), ("3. Ocupación, Quiebres & Dead Stock", ft.Icons.PIE_CHART_OUTLINE_ROUNDED)]),
            ("Recepción\n(Ingresos PO)", ft.Icons.CHECK_BOX_OUTLINED, recep.vista, recep.cargar_lista_asns, recep.sel_sub_inb, [("1. Recepción Activa (PO)", ft.Icons.FACT_CHECK_OUTLINED), ("2. Consultas de Recepción", ft.Icons.MANAGE_SEARCH_ROUNDED), ("3. Control Calidad (QA por PO)", ft.Icons.VERIFIED_USER_OUTLINED), ("4. Modificación de PO y LPNs", ft.Icons.EDIT_NOTE_ROUNDED)]),
            ("Almacenamiento\n(Mov. LPN)", ft.Icons.ACCOUNT_TREE_OUTLINED, puta.vista, puta.cargar_inventario_ubicaciones, puta.sel_sub_put, [("1. Putaway & Mapa de Stock", ft.Icons.DOMAIN_OUTLINED), ("2. Reabastecimiento (Reserva -> N1)", ft.Icons.ARROW_DOWNWARD_ROUNDED), ("3. Vista Combinada", ft.Icons.VIEW_AGENDA_OUTLINED), ("4. Gemelo Digital 3D", ft.Icons.VIEW_IN_AR_ROUNDED)]),
            ("Olas\n(Packing)", ft.Icons.VIEW_IN_AR_OUTLINED, pick.vista, pick.cargar_monitor_packing_dual, pick.sel_sub_olas, [("1. Monitor Completo (Olas + Packing)", ft.Icons.VIEW_QUILT_OUTLINED), ("2. Extracción Olas NetSuite", ft.Icons.CLOUD_DOWNLOAD_OUTLINED), ("3. Estaciones Packing (Normal / -FA)", ft.Icons.INVENTORY_OUTLINED)]),
            ("Mov. Stock\n(Inventario)", ft.Icons.LIBRARY_BOOKS_OUTLINED, inv.vista, None, inv.sel_sub_inventario, [
                ("1. Pasillos y Cruce ERP", ft.Icons.RULE_ROUNDED),
                ("2. SKU Dirigido & Ubic. Vacías", ft.Icons.TRACK_CHANGES_ROUNDED),
                ("3. Trazabilidad LPN / Rack", ft.Icons.HISTORY_ROUNDED),
                ("4. Alertas y Desvíos (RF)", ft.Icons.WARNING_AMBER_ROUNDED),
            ]),
            ("Admin & Maestra\n(Usuarios / SKU)", ft.Icons.ADMIN_PANEL_SETTINGS_OUTLINED, mae.vista, mae.cargar_maestra_skus, mae.sel_sub_maestra, [
                ("1. Usuarios y Accesos (PC / RF)", ft.Icons.MANAGE_ACCOUNTS_ROUNDED),
                ("2. Catálogo Maestro y Enrolamiento", ft.Icons.INVENTORY_2_OUTLINED),
            ]),
            ("Etiquetas\n(Impresión)", ft.Icons.HANDYMAN_OUTLINED, imp.vista, None, imp.sel_sub_imp, [("1. Imprimir LPN", ft.Icons.QR_CODE_2_ROUNDED), ("2. Ubicación / Tótem", ft.Icons.LOCATION_ON_OUTLINED), ("3. Etiquetas Cencosud", ft.Icons.LOCAL_MALL_OUTLINED), ("4. Etiquetas Mercado Libre", ft.Icons.LOCAL_SHIPPING_OUTLINED)]),
        ]

        COLOR_BG_PORTAL = "#527976"
        COLOR_PANEL_IZQ = "#2F3738"
        COLOR_HEADER = "#34302D"

        contenedor_vista_activa = ft.Container(expand=True)
        panel_submenus = ft.Container(width=250, visible=False)

        def registrar_visita_reciente(idx_mod: int, sub_idx: int = 0):
            nombre_m = vistas_mapa[idx_mod][0].replace("\n", " ")
            sub_items = vistas_mapa[idx_mod][5]
            nombre_sub = sub_items[sub_idx][0] if 0 <= sub_idx < len(sub_items) else ""
            hora_actual = time.strftime("%H:%M")
            etiqueta = f"{nombre_m} • {nombre_sub}"
            historial_recientes[:] = [h for h in historial_recientes if not (h[0] == idx_mod and h[1] == sub_idx)]
            historial_recientes.insert(0, (idx_mod, sub_idx, etiqueta, hora_actual))
            if len(historial_recientes) > 6:
                historial_recientes.pop()

        def generar_menu_lateral(idx_mod: int):
            texto_mod, icono_mod, _, _, fn_sub, sub_items = vistas_mapa[idx_mod]
            items = []
            for s_idx, (txt_sub, ico_sub) in enumerate(sub_items):
                items.append(
                    ft.ListTile(
                        leading=ft.Icon(ico_sub, color="#38BDF8", size=19),
                        title=ft.Text(txt_sub, size=12, color="#F8FAFC", weight=ft.FontWeight.W_500),
                        on_click=lambda e, m=idx_mod, s=s_idx, fn=fn_sub: (
                            registrar_visita_reciente(m, s),
                            fn(s) if fn else None,
                            page.update(),
                        ),
                        hover_color="#527976",
                    )
                )
            return ft.Container(
                width=250,
                bgcolor="#2F3738",
                border=ft.Border(right=ft.BorderSide(1, "#3B484B")),
                content=ft.Column(
                    [
                        ft.Container(
                            padding=18,
                            bgcolor="#232A2B",
                            border=ft.Border(bottom=ft.BorderSide(1, "#3B484B")),
                            content=ft.Row([
                                ft.Icon(icono_mod, color="#38BDF8", size=22),
                                ft.Text(texto_mod.replace("\n", " "), size=13, weight=ft.FontWeight.BOLD, color="#FFFFFF")
                            ], spacing=12)
                        ),
                        ft.Column(items, spacing=2)
                    ],
                    spacing=0
                )
            )
        def activar_modulo_principal(idx_sel: int, sub_idx: int = 0):
         codigos_mod = ["PC_DASHBOARD", "PC_RECEPCION", "PC_ALMACENAMIENTO", "PC_OLAS", "PC_INVENTARIO", "PC_ADMIN_MAESTRA", "PC_IMPRESION"]
         rol_usr = str(getattr(page, "rol_actual", "")).upper()
         permisos_str = str(getattr(page, "modulos_pc_usuario", "")).upper()
         if "ADMIN" not in rol_usr and permisos_str and codigos_mod[idx_sel] not in permisos_str:
             notificar_global(page, "Acceso restringido: tu perfil no tiene permisos para este módulo.", "#B91C1C")
             return
         
        def activar_modulo_principal(idx_sel: int, sub_idx: int = 0):
            nonlocal indice_modulo_activo
            indice_modulo_activo = idx_sel
            registrar_visita_reciente(idx_sel, sub_idx)
            panel_submenus.content = generar_menu_lateral(idx_sel)
            panel_submenus.visible = True
            contenedor_vista_activa.content = vistas_mapa[idx_sel][2]
            accion_recarga = vistas_mapa[idx_sel][3]
            fn_sub = vistas_mapa[idx_sel][4]
            if fn_sub:
                fn_sub(sub_idx)
            if accion_recarga:
                accion_recarga()
            page.bgcolor = "#1B2122"
            btn_home.visible = True
            cuerpo_principal.content = ft.Row([panel_submenus, contenedor_vista_activa], expand=True, spacing=0)
            adaptar_resolucion_automatica()
            page.update()

        def volver_al_home(e=None):
            nonlocal indice_modulo_activo
            indice_modulo_activo = -1
            btn_home.visible = False
            page.bgcolor = COLOR_BG_PORTAL
            cargar_datos_vivos_panel_izquierdo()
            cuerpo_principal.content = vista_portal_home
            page.update()

        # --- LAS "TRES RAYAS" (MENÚ HAMBURGUESA CON ACCIÓN EN HOME Y EN MÓDULOS) ---
        def toggle_menu_tres_rayas(e=None):
            if indice_modulo_activo == -1:
                panel_perfil.visible = not panel_perfil.visible
            else:
                panel_submenus.visible = not panel_submenus.visible
            page.update()

        botones_grid = []
        for idx, (texto_mod, icono_mod, _, _, _, _) in enumerate(vistas_mapa):
            botones_grid.append(
                ft.Container(
                    width=130, height=130,
                    on_click=lambda e, i=idx: activar_modulo_principal(i),
                    ink=True, border_radius=8,
                    content=ft.Column(
                        [
                            ft.Icon(icono_mod, size=55, color=ft.Colors.WHITE),
                            ft.Text(texto_mod, size=14, weight=ft.FontWeight.W_500, color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER)
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=15
                    )
                )
            )

        usuario_logueado = getattr(page, "usuario_actual", "Operador")
        rol_logueado = getattr(page, "rol_actual", "Administrador WMS")

        # --- LOGO CIRCULAR DE LUDIPEK (Sin nombre debajo) ---
        tiene_logo = os.path.exists(os.path.join("assets", "logo.png"))
        avatar_logo = ft.Container(
            width=130, height=130,
            border_radius=65,
            bgcolor=ft.Colors.WHITE,
            alignment=ft.Alignment.CENTER,
            padding=12,
            shadow=ft.BoxShadow(blur_radius=14, color="#40000000", offset=ft.Offset(0, 4)),
            content=(
                ft.Image(src="/logo.png", width=100, height=100)
                if tiene_logo
                else ft.Icon(ft.Icons.PETS_ROUNDED, size=72, color=COLOR_PANEL_IZQ)
            )
        )

        # --- GATITO REALISTA ANIMADO (Sprites de alta definición en assets/) ---
        tiene_sprites_gato = os.path.exists(os.path.join("assets", "cat_walk_0.png"))
        img_gato_realista = ft.Image(
            src="/cat_walk_0.png" if tiene_sprites_gato else "/logo.png",
            width=125,
            height=74,
            gapless_playback=True,
        )

        burbuja_miau = ft.Container(
            visible=False,
            bgcolor="#232A2B",
            padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            border_radius=14,
            border=ft.Border.all(1.5, "#38BDF8"),
            shadow=ft.BoxShadow(blur_radius=10, color="#40000000", offset=ft.Offset(0, 3)),
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.PETS_ROUNDED, color="#38BDF8", size=16),
                    ft.Text("¡Miau! Bodega Ludipek sincronizada y en orden", size=12, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                ],
                spacing=6,
                tight=True,
            ),
        )

        actor_gato = ft.Container(
            visible=True,
            margin=ft.Margin.only(left=0),
            on_click=lambda e: (
                setattr(img_gato_realista, "src", "/cat_sit.png"),
                setattr(burbuja_miau, "visible", not burbuja_miau.visible),
                page.update(),
            ),
            tooltip="Haz clic para saludar al gato guardián",
            content=ft.Row(
                [
                    img_gato_realista,
                    burbuja_miau,
                ],
                tight=True,
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        paseo_en_curso = False

        def pasear_gatito_sync():
            nonlocal paseo_en_curso
            if paseo_en_curso or not sesion_activa or indice_modulo_activo != -1:
                return
            paseo_en_curso = True
            try:
                actor_gato.visible = True
                burbuja_miau.visible = False
                ancho_max = max(520, int((page.width or 1280) - 480))
                mitad = ancho_max // 2
                paso = 0
                for pos_x in range(0, ancho_max, 9):
                    if not sesion_activa or indice_modulo_activo != -1:
                        break
                    paso += 1
                    actor_gato.margin = ft.Margin.only(left=pos_x)
                    if tiene_sprites_gato:
                        img_gato_realista.src = f"/cat_walk_{paso % 6}.png"

                    if abs(pos_x - mitad) < 9:
                        if tiene_sprites_gato:
                            img_gato_realista.src = "/cat_sit.png"
                        burbuja_miau.visible = True
                        page.update()
                        time.sleep(2.6)
                        burbuja_miau.visible = False
                    else:
                        page.update()
                        time.sleep(0.065)

                actor_gato.visible = False
                page.update()
            except Exception:
                pass
            finally:
                paseo_en_curso = False

        def loop_mascota_background():
            time.sleep(1.5)
            while sesion_activa:
                if indice_modulo_activo == -1:
                    pasear_gatito_sync()
                time.sleep(24)

        # --- PANEL IZQUIERDO INTERACTIVO: ACTIVITY | RECENT | FAVORITES + ANNOUNCEMENTS ---
        tab_activa_izq = "ACTIVITY"
        lbl_estado_proceso = ft.Text(
            "El proceso de planificación 2026 está activo y conectado.",
            size=12,
            color="#E2E8F0",
        )
        txt_badge_anuncios = ft.Text("0", color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, size=11)
        col_contenido_tab_izq = ft.Column(spacing=6)
        col_lista_anuncios = ft.Column(spacing=6, visible=True)

        btn_tab_activity = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=6,
            bgcolor="#527976",
            ink=True,
            content=ft.Text("Activity", color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, size=12),
        )
        btn_tab_recent = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=6,
            bgcolor="transparent",
            ink=True,
            content=ft.Text("Recent", color="#94A3B8", weight=ft.FontWeight.W_500, size=12),
        )
        btn_tab_favorites = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=6,
            bgcolor="transparent",
            ink=True,
            content=ft.Text("Favorites", color="#94A3B8", weight=ft.FontWeight.W_500, size=12),
        )

        def crear_item_panel_izq(icono, titulo, subtitulo, color_ico, fn_click):
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=10, vertical=7),
                bgcolor="#232A2B",
                border_radius=6,
                border=ft.Border.all(1, "#3B484B"),
                ink=True,
                on_click=fn_click,
                content=ft.Row(
                    [
                        ft.Icon(icono, color=color_ico, size=16),
                        ft.Column(
                            [
                                ft.Text(titulo, size=11, weight=ft.FontWeight.BOLD, color="#F8FAFC"),
                                ft.Text(subtitulo, size=10, color="#94A3B8"),
                            ],
                            spacing=1,
                            expand=True,
                        ),
                        ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color="#64748B", size=16),
                    ],
                    spacing=8,
                ),
            )

        def cargar_datos_vivos_panel_izquierdo(e=None):
            try:
                res_pos = supabase.table("asn_cabecera").select("id, codigo_asn, numero_oc, proveedor, estado").neq("estado", "COMPLETADO").order("id", desc=True).limit(5).execute()
                pos_activas = res_pos.data or []
                res_lpns = supabase.table("registro_recepcion").select("id, lpn, sku, unidades_totales, lote").order("id", desc=True).limit(5).execute()
                ultimos_lpns = res_lpns.data or []

                lbl_estado_proceso.value = (
                    f"Proceso 2026 activo • {len(pos_activas)} POs en curso y {len(ultimos_lpns)} LPNs recientes."
                )

                # Construir Anuncios reales (Announcements)
                anuncios_items = []
                if pos_activas:
                    po_top = pos_activas[0]
                    cod_top = po_top.get("numero_oc") or po_top.get("codigo_asn") or "PO"
                    anuncios_items.append(
                        crear_item_panel_izq(
                            ft.Icons.LOCAL_SHIPPING_OUTLINED,
                            f"{len(pos_activas)} POs en Recepción Activa",
                            f"Última: {cod_top} ({str(po_top.get('proveedor',''))[:18]})",
                            "#38BDF8",
                            lambda ev: activar_modulo_principal(1, 0),
                        )
                    )
                cuarentenas = [r for r in ultimos_lpns if "CUARENTENA" in str(r.get("lote", "")).upper() or "RECHAZADO" in str(r.get("lote", "")).upper()]
                if cuarentenas:
                    anuncios_items.append(
                        crear_item_panel_izq(
                            ft.Icons.WARNING_AMBER_ROUNDED,
                            f"{len(cuarentenas)} Lotes en Cuarentena QA",
                            "Clic para liberar o inspeccionar en QA",
                            "#FBBF24",
                            lambda ev: activar_modulo_principal(1, 2),
                        )
                    )
                else:
                    anuncios_items.append(
                        crear_item_panel_izq(
                            ft.Icons.VERIFIED_ROUNDED,
                            "Control de Calidad QA al día",
                            f"ERP NetSuite: {'Conectado' if NETSUITE_CONECTADO else 'Modo Cloud'}",
                            "#34D399",
                            lambda ev: activar_modulo_principal(0, 0),
                        )
                    )

                txt_badge_anuncios.value = str(len(anuncios_items))
                col_lista_anuncios.controls = anuncios_items

                # Construir contenido según pestaña activa (Activity | Recent | Favorites)
                col_contenido_tab_izq.controls.clear()
                if tab_activa_izq == "ACTIVITY":
                    if ultimos_lpns:
                        for r in ultimos_lpns[:3]:
                            col_contenido_tab_izq.controls.append(
                                crear_item_panel_izq(
                                    ft.Icons.QR_CODE_2_ROUNDED,
                                    f"{r.get('lpn', 'LPN')} • {r.get('sku', '')}",
                                    f"Recibido: {r.get('unidades_totales', 0)} UN en andén",
                                    "#38BDF8",
                                    lambda ev: activar_modulo_principal(1, 0),
                                )
                            )
                    else:
                        col_contenido_tab_izq.controls.append(
                            ft.Text("Sin recepciones recientes registradas.", size=11, color="#94A3B8")
                        )
                elif tab_activa_izq == "RECENT":
                    if historial_recientes:
                        for m_i, s_i, etiq, h_str in historial_recientes[:3]:
                            col_contenido_tab_izq.controls.append(
                                crear_item_panel_izq(
                                    ft.Icons.HISTORY_ROUNDED,
                                    etiq[:28],
                                    f"Visitado a las {h_str}",
                                    "#A78BFA",
                                    lambda ev, mi=m_i, si=s_i: activar_modulo_principal(mi, si),
                                )
                            )
                    else:
                        col_contenido_tab_izq.controls.append(
                            ft.Text("Aún no has abierto módulos en esta sesión.", size=11, color="#94A3B8")
                        )
                elif tab_activa_izq == "FAVORITES":
                    favoritos_fijos = [
                        (ft.Icons.FACT_CHECK_OUTLINED, "Recepción 3-Way Match", "Conciliar PO vs Andén RF", 1, 0),
                        (ft.Icons.VIEW_IN_AR_ROUNDED, "Gemelo Digital 3D", "Mapa interactivo de Racks", 2, 3),
                        (ft.Icons.QR_CODE_2_ROUNDED, "Imprimir LPN 15x10", "Etiquetas térmicas de pallet", 6, 0),
                    ]
                    for ico_f, tit_f, sub_f, m_f, s_f in favoritos_fijos:
                        col_contenido_tab_izq.controls.append(
                            crear_item_panel_izq(
                                ico_f,
                                tit_f,
                                sub_f,
                                "#34D399",
                                lambda ev, mf=m_f, sf=s_f: activar_modulo_principal(mf, sf),
                            )
                        )
            except Exception:
                pass

        def seleccionar_tab_izq(nueva_tab: str):
            nonlocal tab_activa_izq
            tab_activa_izq = nueva_tab
            for cod_t, btn_t in [("ACTIVITY", btn_tab_activity), ("RECENT", btn_tab_recent), ("FAVORITES", btn_tab_favorites)]:
                activo = cod_t == nueva_tab
                btn_t.bgcolor = "#527976" if activo else "transparent"
                btn_t.content.color = ft.Colors.WHITE if activo else "#94A3B8"
                btn_t.content.weight = ft.FontWeight.BOLD if activo else ft.FontWeight.W_500
            cargar_datos_vivos_panel_izquierdo()
            page.update()

        btn_tab_activity.on_click = lambda e: seleccionar_tab_izq("ACTIVITY")
        btn_tab_recent.on_click = lambda e: seleccionar_tab_izq("RECENT")
        btn_tab_favorites.on_click = lambda e: seleccionar_tab_izq("FAVORITES")

        panel_perfil = ft.Container(
            width=320,
            bgcolor=COLOR_PANEL_IZQ,
            padding=ft.Padding.symmetric(horizontal=26, vertical=24),
            content=ft.Column(
                [
                    ft.Container(
                        alignment=ft.Alignment.CENTER,
                        margin=ft.Margin.only(top=6, bottom=14),
                        content=avatar_logo,
                    ),
                    ft.Row(
                        [
                            ft.Text("Planning Process", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH_ROUNDED,
                                icon_color="#94A3B8",
                                icon_size=18,
                                tooltip="Actualizar actividad en vivo",
                                on_click=lambda e: (cargar_datos_vivos_panel_izquierdo(), page.update()),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(color="#475569", height=1),
                    lbl_estado_proceso,
                    ft.Container(height=8),
                    ft.Row([btn_tab_activity, btn_tab_recent, btn_tab_favorites], spacing=6),
                    ft.Divider(color="#475569", height=1),
                    col_contenido_tab_izq,
                    ft.Container(height=6),
                    ft.Container(
                        ink=True,
                        on_click=lambda e: (setattr(col_lista_anuncios, "visible", not col_lista_anuncios.visible), page.update()),
                        content=ft.Row(
                            [
                                ft.Container(
                                    bgcolor="#0284C7", width=22, height=22, border_radius=11,
                                    alignment=ft.Alignment.CENTER, content=txt_badge_anuncios,
                                ),
                                ft.Text("Announcements", color=ft.Colors.WHITE, size=13, weight=ft.FontWeight.BOLD, expand=True),
                                ft.Icon(ft.Icons.EXPAND_MORE_ROUNDED, color="#94A3B8", size=18),
                            ],
                            spacing=8,
                        ),
                    ),
                    col_lista_anuncios,
                    ft.Container(expand=True),
                    ft.Divider(color="#475569", height=1),
                    ft.Container(
                        alignment=ft.Alignment.CENTER,
                        on_click=lambda e: threading.Thread(target=pasear_gatito_sync, daemon=True).start(),
                        ink=True,
                        padding=4,
                        border_radius=8,
                        tooltip="Invocar al gato guardián de Ludipek",
                        content=ft.Column([
                            ft.Icon(ft.Icons.PLAY_CIRCLE_FILL_ROUNDED, color="#38BDF8", size=24),
                            ft.Text("Tour", color=ft.Colors.WHITE, size=11, weight=ft.FontWeight.BOLD)
                        ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                    )
                ],
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            )
        )

        vista_portal_home = ft.Row(
            [
                panel_perfil,
                ft.Container(
                    expand=True,
                    padding=ft.Padding.only(left=80, top=55, right=60, bottom=20),
                    alignment=ft.Alignment.TOP_LEFT,
                    content=ft.Column(
                        [
                            ft.Row(botones_grid, wrap=True, spacing=40, run_spacing=45, alignment=ft.MainAxisAlignment.START),
                            ft.Container(height=55),
                            ft.Container(
                                height=85,
                                alignment=ft.Alignment.CENTER_LEFT,
                                content=actor_gato,
                            ),
                        ],
                        spacing=10,
                    ),
                )
            ], spacing=0, expand=True
        )

        cuerpo_principal = ft.Container(content=vista_portal_home, expand=True)
        btn_home = ft.IconButton(icon=ft.Icons.HOME_OUTLINED, icon_color=ft.Colors.WHITE, tooltip="Volver al Portal de Inicio", on_click=volver_al_home, visible=False)

        # --- MENÚ RÁPIDO DE MÓDULOS (Icono de 9 cuadritos APPS_ROUNDED) ---
        menu_apps_rapido = ft.PopupMenuButton(
            icon=ft.Icons.APPS_ROUNDED,
            icon_color=ft.Colors.WHITE,
            tooltip="Acceso rápido a los 7 módulos WMS",
            items=[
                ft.PopupMenuItem(
                    content=ft.Text("🏠 Portal de Inicio (Home)"),
                    on_click=volver_al_home,
                ),
            ] + [
                ft.PopupMenuItem(
                    content=ft.Text(f"{idx + 1}. {texto_m.replace(chr(10), ' ')}"),
                    on_click=lambda e, i=idx: activar_modulo_principal(i),
                )
                for idx, (texto_m, _, _, _, _, _) in enumerate(vistas_mapa)
            ],
        )

        def cerrar_sesion_actual(e=None):
            nonlocal sesion_activa
            sesion_activa = False
            mostrar_pantalla_login()

        # --- MENÚ DE PERFIL Y ESTADO DE SISTEMA (Icono de Usuario + Nombre ▼) ---
        menu_usuario_header = ft.PopupMenuButton(
            tooltip="Perfil de Usuario y Sesión",
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.PERSON_OUTLINE, color=ft.Colors.WHITE, size=20),
                    ft.Text(f"{usuario_logueado.lower()} ▼", color=ft.Colors.WHITE, size=12, weight=ft.FontWeight.W_600),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            items=[
                ft.PopupMenuItem(content=ft.Text(f"👤 {usuario_logueado} ({rol_logueado})")),
                ft.PopupMenuItem(content=ft.Text("☁️ Supabase Cloud: CONECTADO")),
                ft.PopupMenuItem(content=ft.Text(f"🔗 NetSuite ERP: {'CONECTADO' if NETSUITE_CONECTADO else 'DESCONECTADO'}")),
                ft.PopupMenuItem(
                    content=ft.Text("🐾 Pasear Gato Guardián Ludipek"),
                    on_click=lambda e: (volver_al_home(), threading.Thread(target=pasear_gatito_sync, daemon=True).start()),
                ),
                ft.PopupMenuItem(
                    content=ft.Text("🚪 Cerrar Sesión"),
                    on_click=cerrar_sesion_actual,
                ),
            ],
        )

        encabezado = ft.Container(
            bgcolor=COLOR_HEADER, padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            content=ft.Row([
                ft.Row([
                    ft.IconButton(
                        icon=ft.Icons.MENU,
                        icon_color=ft.Colors.WHITE,
                        tooltip="Mostrar / Ocultar Panel Lateral (Modo Pantalla Completa)",
                        on_click=toggle_menu_tres_rayas,
                    ),
                    ft.Container(
                        ink=True,
                        on_click=volver_al_home,
                        tooltip="Ir al Inicio",
                        content=ft.Row([
                            ft.Text("LUDIPEK", color=ft.Colors.WHITE, size=18, weight=ft.FontWeight.W_900),
                            ft.Container(width=10),
                            ft.Text("WMS Ludipek", color="#94A3B8", size=13),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([
                    btn_home,
                    menu_apps_rapido,
                    menu_usuario_header,
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        )

        def adaptar_resolucion_automatica(e=None):
            ancho_w = page.width or 1366
            alto_h = page.height or 768
            es_notebook = (ancho_w < 1480) or (alto_h < 850)
            pad_vista = 10 if es_notebook else 18
            pad_tarjeta = 10 if es_notebook else 14

            dash.vista.padding = pad_vista
            recep.vista.padding = pad_vista
            puta.vista.padding = pad_vista
            pick.vista.padding = pad_vista
            inv.vista.padding = pad_vista
            mae.vista.padding = pad_vista
            imp.vista.padding = pad_vista

            for tarj in tarjetas_adaptables:
                tarj.padding = pad_tarjeta
            for card_k, box_ico, txt_val in kpis_adaptables:
                card_k.padding = 8 if es_notebook else 12
                box_ico.padding = 6 if es_notebook else 10
                txt_val.size = 16 if es_notebook else 20
            page.update()

        cargar_datos_vivos_panel_izquierdo()
        page.on_resize = adaptar_resolucion_automatica
        page.controls.clear()
        page.overlay.clear()
        page.bgcolor = COLOR_BG_PORTAL
        page.add(ft.Column([encabezado, cuerpo_principal], spacing=0, expand=True))
        adaptar_resolucion_automatica()
        threading.Thread(target=loop_mascota_background, daemon=True).start()

if __name__ == "__main__":
    os.makedirs(os.path.join("assets", "uploads"), exist_ok=True)
    os.makedirs(os.path.join("assets", "descargas"), exist_ok=True)
    if not os.environ.get("FLET_SECRET_KEY"):
        os.environ["FLET_SECRET_KEY"] = os.environ.get("WMS_PASSWORD_SALT", "ludipek_secret_upload_key_2026")

    puerto_cloud = int(os.environ.get("PORT", 8557))
    ft.run(
        main,
        view=ft.AppView.WEB_BROWSER,
        port=puerto_cloud,
        host="0.0.0.0",
        assets_dir="assets",
        upload_dir=os.path.join("assets", "uploads"),
    )