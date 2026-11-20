import os
import math
import time
import shutil
import threading
import traceback
import flet as ft
from datetime import datetime
from dependencias import *
from modulos import m0_dashboard, m1_recepcion, m2_putaway, m3_picking, m4_inventario, m5_maestra, m6_impresion, m7_ruteo_facturacion, m8_recepcion_ccp
os.environ["TZ"] = "America/Santiago"
if hasattr(time, "tzset"):
    time.tzset()


def _ico(*nombres_candidatos):
    """Devuelve siempre un icono válido en la versión instalada de Flet sin arrojar error."""
    for nom in nombres_candidatos:
        limpio = str(nom or "").replace("ft.Icons.", "").replace("Icons.", "").strip()
        val = getattr(ft.Icons, limpio, None)
        if val is not None:
            return val
    return ft.Icons.WIDGETS_OUTLINED


def dibujar_frame_gato_realista(phase: float, sitting: bool = False):
    from PIL import Image, ImageDraw, ImageFilter

    W, H = 440, 260
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    if not sitting:
        sdraw.ellipse([95, 218, 335, 242], fill=(15, 23, 42, 95))
    else:
        sdraw.ellipse([140, 218, 310, 242], fill=(15, 23, 42, 105))
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    img.alpha_composite(shadow)

    draw = ImageDraw.Draw(img)

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

        draw_limb(leg_kinematics(138, 138 + bob, math.pi, False), [20, 13, 9], FUR_SHADOW, WHITE_SHADE)
        draw_limb(leg_kinematics(272, 142 + bob, math.pi * 1.5, True), [18, 12, 8.5], FUR_SHADOW, WHITE_SHADE)

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

        draw.ellipse([105, 92 + bob, 215, 172 + bob], fill=FUR_DARK)
        draw.ellipse([215, 96 + bob, 312, 178 + bob], fill=FUR_DARK)
        draw.polygon([(155, 93 + bob), (275, 97 + bob), (285, 174 + bob), (145, 168 + bob)], fill=FUR_DARK)
        draw.pieslice([235, 108 + bob, 316, 178 + bob], start=-45, end=75, fill=WHITE_FUR)
        draw.chord([125, 94 + bob, 290, 145 + bob], start=185, end=355, fill=FUR_MID)
        draw.chord([145, 96 + bob, 270, 128 + bob], start=190, end=350, fill=FUR_LIGHT)

        draw_limb(leg_kinematics(144, 138 + bob, 0.0, False), [22, 14, 9.5], FUR_DARK, WHITE_FUR)
        draw_limb(leg_kinematics(278, 142 + bob, math.pi * 0.5, True), [19, 12.5, 9], FUR_DARK, WHITE_FUR)

        head_cx, head_cy = 315, 92 + bob * 0.7
    else:
        draw.arc([95, 185, 235, 236], start=110, end=290, fill=FUR_DARK, width=22)
        draw.ellipse([145, 118, 255, 226], fill=FUR_DARK)
        draw.polygon([(175, 130), (265, 95), (295, 175), (215, 224)], fill=FUR_DARK)
        draw.ellipse([210, 92, 305, 188], fill=FUR_DARK)
        draw.ellipse([242, 112, 306, 185], fill=WHITE_FUR)
        draw_limb([(255, 150), (262, 190), (268, 224)], [17, 12, 9], FUR_SHADOW, WHITE_SHADE)
        draw_limb([(274, 152), (282, 192), (288, 224)], [18, 13, 9.5], FUR_DARK, WHITE_FUR)
        head_cx, head_cy = 292, 78

    draw.polygon(
        [(head_cx - 32, head_cy + 22), (head_cx + 12, head_cy + 36), (head_cx + 6, head_cy + 46), (head_cx - 38, head_cy + 31)],
        fill=COLLAR_TEAL,
    )
    bx, by = head_cx + 8, head_cy + 44
    draw.ellipse([bx - 8, by - 8, bx + 8, by + 8], fill=GOLD_BELL, outline=(161, 98, 7, 255), width=2)

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

    if os.path.exists(ruta_logo_assets):
        try:
            with Image.open(ruta_logo_assets).convert("RGBA") as im_logo:
                im_logo.resize((64, 64), Image.Resampling.LANCZOS).save(
                    os.path.join("assets", "favicon.png"), format="PNG"
                )
                im_logo.resize((180, 180), Image.Resampling.LANCZOS).save(
                    os.path.join("assets", "icons", "loading-animation.png"), format="PNG"
                )
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

    # Sprites del gato guardián (Ida hacia la derecha y vuelta hacia la izquierda)
    try:
        for idx_f in range(6):
            ruta_f = os.path.join("assets", f"cat_walk_{idx_f}.png")
            if not os.path.exists(ruta_f):
                im_f = dibujar_frame_gato_realista(phase=(idx_f / 6.0) * 2 * math.pi, sitting=False)
                im_f.save(ruta_f, format="PNG")
            else:
                im_f = Image.open(ruta_f).convert("RGBA")

            ruta_left = os.path.join("assets", f"cat_walk_left_{idx_f}.png")
            if not os.path.exists(ruta_left):
                im_left = im_f.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                im_left.save(ruta_left, format="PNG")

        ruta_sit = os.path.join("assets", "cat_sit.png")
        if not os.path.exists(ruta_sit):
            im_s = dibujar_frame_gato_realista(phase=0.0, sitting=True)
            im_s.save(ruta_sit, format="PNG")
    except Exception as ex_cat:
        print(f"[WARN] No se pudieron generar los sprites realistas del gato: {ex_cat}")


preparar_assets_visuales()


class MonitorUsuariosColaModulo:
    """Módulo principal independiente para supervisar Operadores RF/PC activos y asignar la Cola de Picking en vivo."""

    def __init__(self, page: ft.Page, tarjetas_adaptables: list, kpis_adaptables: list):
        self.page = page
        self.tarjetas_adaptables = tarjetas_adaptables
        self.kpis_adaptables = kpis_adaptables

        BG_MODULO = "#1B2122"
        BG_CARD = "#262E30"
        BG_INPUT = "#1D2426"
        BG_DIGITAL = "#121718"
        BORDER_COLOR = "#3B484B"
        ACCENT_CYAN = "#38BDF8"
        ACCENT_BLUE = "#0284C7"
        TEXT_WHITE = "#FFFFFF"
        TEXT_MUTED = "#94A3B8"

        lbl_kpi_usr_activos = ft.Text("0", size=18, weight=ft.FontWeight.W_900, color="#34D399", font_family="Consolas")
        lbl_kpi_cola_pend = ft.Text("0", size=18, weight=ft.FontWeight.W_900, color="#FBBF24", font_family="Consolas")
        lbl_kpi_en_pack = ft.Text("0", size=18, weight=ft.FontWeight.W_900, color=ACCENT_CYAN, font_family="Consolas")
        lbl_kpi_movs_hoy = ft.Text("0", size=18, weight=ft.FontWeight.W_900, color=TEXT_WHITE, font_family="Consolas")

        txt_buscar_cola = ft.TextField(
            label="Filtrar Operador, N° OV o Cliente...",
            width=250,
            dense=True,
            text_size=12,
            color=TEXT_WHITE,
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=ACCENT_CYAN,
            label_style=ft.TextStyle(size=11, color=TEXT_MUTED),
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            border_radius=6,
        )

        def caja_kpi(txt_ctrl: ft.Text, titulo: str, color_borde: str):
            return ft.Container(
                width=155,
                height=64,
                bgcolor=BG_DIGITAL,
                border_radius=8,
                border=ft.Border.all(1.5, color_borde),
                padding=8,
                content=ft.Column(
                    [
                        txt_ctrl,
                        ft.Text(titulo, size=10, color=TEXT_MUTED, weight=ft.FontWeight.BOLD),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=2,
                ),
            )

        tabla_usuarios_rf = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=36,
            data_row_max_height=42,
            column_spacing=14,
            horizontal_margin=10,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("OPERADOR / USUARIO", weight=ft.FontWeight.BOLD, size=10.5, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("ROL", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("BODEGA", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("OV ASIGNADA (ACTIVA / COLA)", weight=ft.FontWeight.BOLD, size=10, color="#FBBF24")),
                ft.DataColumn(ft.Text("ÚLTIMA ACCIÓN RF", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("MOVIMIENTOS", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("UNID. PROCESADAS", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
            ],
            rows=[],
        )

        tabla_cola_picking = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=40,
            data_row_max_height=46,
            column_spacing=14,
            horizontal_margin=10,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("PRIORIDAD", weight=ft.FontWeight.BOLD, size=10, color="#A78BFA")),
                ft.DataColumn(ft.Text("OV / OT EN COLA", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("CANAL", weight=ft.FontWeight.BOLD, size=10, color="#FBBF24")),
                ft.DataColumn(ft.Text("FECHA OV", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("CLIENTE / DESTINO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ETAPA EN COLA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ASIGNAR OPERADOR RF", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("ANULAR", weight=ft.FontWeight.BOLD, size=10, color="#F87171")),
            ],
            rows=[],
        )

        # Sesiones del celular (script 24): qué operador está conectado y desde dónde
        tabla_sesiones_rf = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=36,
            data_row_max_height=42,
            column_spacing=14,
            horizontal_margin=10,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD, size=10, color=col))
                for c, col in (("OPERADOR", ACCENT_CYAN), ("DISPOSITIVO", TEXT_WHITE), ("INICIO", "#34D399"),
                               ("ÚLTIMO USO", "#34D399"), ("ESTADO", "#FBBF24"), ("ACCIÓN", "#F87171"))
            ],
            rows=[],
        )
        lbl_modo_sesion = ft.Text("", size=11, color=TEXT_MUTED)

        cont_tabla_usuarios = envolver_tabla_scroll(tabla_usuarios_rf, 240)
        cont_tabla_cola = envolver_tabla_scroll(tabla_cola_picking, 320)
        cont_tabla_sesiones = envolver_tabla_scroll(tabla_sesiones_rf, 200)

        def es_admin_pc() -> bool:
            return "ADMIN" in str(getattr(self.page, "rol_actual", "") or "").upper()

        def abrir_anular_ov(id_ov, num_ov: str, cliente: str):
            if not es_admin_pc():
                notificar_global(self.page, "Solo un administrador puede anular órdenes.", "#B91C1C")
                return
            txt_motivo = ft.TextField(label="Motivo (obligatorio)", multiline=True, min_lines=2, max_lines=3, width=420,
                                      text_size=12, color=TEXT_WHITE, bgcolor=BG_INPUT, border_color=BORDER_COLOR)
            lbl_err = ft.Text("", size=12, color="#F87171")

            def cerrar(e=None):
                try:
                    self.page.pop_dialog()
                except Exception:
                    pass

            def confirmar(e=None):
                motivo = (txt_motivo.value or "").strip()
                if len(motivo) < 4:
                    lbl_err.value = "Escriba el motivo."
                    self.page.update()
                    return
                try:
                    supabase.rpc("wms_anular_ov", {
                        "p_orden_id": int(id_ov), "p_usuario": str(getattr(self.page, "usuario_actual", "") or ""),
                        "p_motivo": motivo,
                    }).execute()
                except Exception as ex:
                    msg = str(getattr(ex, "message", None) or ex)
                    if "wms_anular_ov" in msg and ("not find" in msg or "does not exist" in msg):
                        msg = "falta ejecutar 25_anular_ov.sql en Supabase"
                    lbl_err.value = f"No se anuló: {msg.replace('WMS: ', '')}"
                    self.page.update()
                    return
                cerrar()
                notificar_global(self.page, f"Orden {num_ov} anulada.", "#047857")
                refrescar_monitor_usuarios_y_cola()

            self.page.show_dialog(ft.AlertDialog(
                modal=True,
                title=ft.Text(f"Anular orden {num_ov}", weight=ft.FontWeight.BOLD),
                content=ft.Container(width=440, content=ft.Column([
                    ft.Text(cliente, size=12.5),
                    ft.Text("La orden sale de la cola de picking y queda ANULADA en el historial con su motivo. "
                            "Solo se puede si no tiene nada pickeado.", size=11.5, color=TEXT_MUTED),
                    txt_motivo, lbl_err,
                ], spacing=10, tight=True)),
                actions=[
                    ft.TextButton("Cancelar", on_click=cerrar),
                    ft.TextButton("ANULAR ORDEN", on_click=confirmar, style=ft.ButtonStyle(color="#F87171")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            ))

        def cerrar_sesion_operador(usuario: str):
            try:
                n = supabase.rpc("wms_cerrar_sesiones_usuario", {"p_usuario": usuario}).execute().data
                notificar_global(self.page, f"Sesión de {usuario} cerrada ({n or 0}). Deberá ingresar su contraseña de nuevo.", "#047857")
            except Exception as ex:
                notificar_global(self.page, f"No se pudo cerrar la sesión: {getattr(ex, 'message', None) or ex}", "#B91C1C")
            refrescar_monitor_usuarios_y_cola()

        def pintar_sesiones():
            try:
                modo = (supabase.table("wms_config").select("valor").eq("clave", "auth_modo").execute().data or [{}])[0].get("valor")
                filas = (supabase.table("wms_sesiones").select("*").order("ultimo_uso", desc=True).limit(80).execute().data or [])
            except Exception:
                lbl_modo_sesion.value = "Sin sesiones verificadas todavía (falta ejecutar 24_sesiones_operador.sql)."
                tabla_sesiones_rf.rows = []
                return
            lbl_modo_sesion.value = ("Modo OBLIGATORIO: sin sesión el celular no puede operar."
                                     if str(modo or "").upper() == "OBLIGATORIO"
                                     else "Modo OPCIONAL (transición): el celular también puede operar sin sesión verificada.")
            ahora = obtener_ahora_chile()
            filas_s = []
            for f in filas:
                inicio_raw = f.get("creada_en")
                try:
                    from datetime import datetime as _dt
                    ini = _dt.fromisoformat(str(inicio_raw).replace("Z", "+00:00"))
                    horas = (ahora - ini).total_seconds() / 3600
                except Exception:
                    horas = 0
                if horas > 24 and f.get("cerrada_en"):
                    continue
                if f.get("cerrada_en"):
                    est, col = "CERRADA", TEXT_MUTED
                elif horas > 14:
                    est, col = "VENCIDA", "#FBBF24"
                else:
                    est, col = "ACTIVA", "#34D399"
                usr = str(f.get("usuario") or "")
                filas_s.append(ft.DataRow(cells=[
                    ft.DataCell(ft.Text(f"{f.get('nombre') or usr} ({usr})", size=11, weight=ft.FontWeight.BOLD, color=ACCENT_CYAN)),
                    ft.DataCell(ft.Text(str(f.get("dispositivo") or "-"), size=10.5)),
                    ft.DataCell(ft.Text(formatear_fecha_hora_chile(inicio_raw), size=10.5)),
                    ft.DataCell(ft.Text(formatear_fecha_hora_chile(f.get("ultimo_uso")), size=10.5)),
                    ft.DataCell(ft.Text(est, size=10.5, weight=ft.FontWeight.BOLD, color=col)),
                    ft.DataCell(ft.IconButton(icon=ft.Icons.LOGOUT_ROUNDED, icon_size=18, icon_color="#F87171",
                                              tooltip="Cerrar la sesión de este operador",
                                              on_click=lambda e, u=usr: cerrar_sesion_operador(u))
                                if est == "ACTIVA" and es_admin_pc() else ft.Text("")),
                ]))
            tabla_sesiones_rf.rows = filas_s

        def asignar_operador_manual_ov(id_ov: int, num_ov: str, nuevo_op: str):
            try:
                supabase.table("netsuite_ordenes_venta").update({"operador_asignado": nuevo_op}).eq("id", id_ov).execute()
                notificar_global(self.page, f"OV {num_ov} asignada a {nuevo_op}.", "#047857")
                refrescar_monitor_usuarios_y_cola()
            except Exception as ex:
                notificar_global(self.page, f"Error asignando OV: {ex}", "#B91C1C")

        def auto_asignar_todas_las_ovs_en_cola(e=None):
            """Reparte las OV sin asignar SOLO entre los usuarios de los equipos Farmacia y Picking (wms_asignar_ovs_por_equipo)."""
            bodega_act = obtener_bodega_activa(self.page)
            try:
                r = supabase.rpc("wms_asignar_ovs_por_equipo", {
                    "p_bodega": bodega_act, "p_por": str(getattr(self.page, "usuario_actual", None) or "PC"),
                }).execute().data or {}
            except Exception as ex:
                msg = getattr(ex, "message", None) or str(ex)
                notificar_global(self.page, f"No se pudo repartir: {msg} (¿falta ejecutar 18_equipos_trabajo.sql?)", "#B91C1C")
                return
            far, pick = int(r.get("farmacia_asignadas") or 0), int(r.get("picking_asignadas") or 0)
            sin_far, sin_pick = int(r.get("farmacia_sin_equipo") or 0), int(r.get("picking_sin_equipo") or 0)
            texto = f"Repartidas: {far} OV de farmacia y {pick} OV normales."
            if sin_far or sin_pick:
                texto += f" Quedan sin asignar {sin_far} de farmacia y {sin_pick} normales: no hay usuarios en ese equipo."
            elif not far and not pick:
                texto = "No hay OV sin asignar en la cola."
            notificar_global(self.page, texto, "#B45309" if (sin_far or sin_pick) else "#047857")
            refrescar_monitor_usuarios_y_cola()

        # ------------------------------------------------------------------
        # EQUIPOS DE TRABAJO: cada usuario en una caja (Farmacia, Picking, ...)
        # ------------------------------------------------------------------
        EQUIPOS = [
            ("SIN_EQUIPO", "Sin equipo", "No recibe OV", "#64748B", "HELP_OUTLINE_ROUNDED"),
            ("FARMACIA", "Picking farmacia", "Recibe OV -FA y OT", "#F59E0B", "LOCAL_PHARMACY_OUTLINED"),
            ("PICKING", "Picking normal", "Recibe OV normales", "#38BDF8", "SHOPPING_CART_OUTLINED"),
            ("PACKING", "Packing", "No recibe OV de picking", "#A78BFA", "INVENTORY_2_OUTLINED"),
            ("RECEPCION", "Recepción y almacenamiento", "No recibe OV de picking", "#34D399", "MOVE_TO_INBOX_ROUNDED"),
            ("INACTIVO", "Inactivo", "No recibe OV", "#EF4444", "BEDTIME_OUTLINED"),
        ]
        fila_equipos = ft.ResponsiveRow(spacing=10, run_spacing=10)

        def mover_usuario_equipo(cod_usuario: str, equipo: str):
            try:
                r = supabase.rpc("wms_mover_usuario_equipo", {
                    "p_usuario": cod_usuario, "p_equipo": None if equipo == "SIN_EQUIPO" else equipo,
                    "p_por": str(getattr(self.page, "usuario_actual", None) or "PC"),
                }).execute().data or {}
            except Exception as ex:
                msg = getattr(ex, "message", None) or str(ex)
                notificar_global(self.page, f"No se movió: {msg} (¿falta ejecutar 18_equipos_trabajo.sql?)", "#B91C1C")
                return
            lib = int(r.get("ov_liberadas") or 0)
            nombre_eq = next((t for k, t, *_ in EQUIPOS if k == equipo), equipo)
            notificar_global(self.page, f"{cod_usuario} pasó a {nombre_eq}."
                             + (f" {lib} OV no iniciadas volvieron a la cola." if lib else ""), "#047857")
            refrescar_monitor_usuarios_y_cola()

        def tarjeta_usuario_equipo(u: dict, equipo_actual: str, ovs: list, actividad: dict):
            cod = str(u.get("usuario") or "").strip().upper()
            nom = str(u.get("nombre_completo") or cod).strip().title()
            # Desplegable de equipo (mismo control que usa la cola de picking)
            menu = ft.Dropdown(
                width=150,
                dense=True,
                value=equipo_actual,
                bgcolor=BG_INPUT,
                border_color=BORDER_COLOR,
                text_style=ft.TextStyle(size=10.5, color=TEXT_WHITE),
                content_padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                options=[ft.DropdownOption(key=k, text=tit) for k, tit, *_ in EQUIPOS],
                on_select=lambda ev, c=cod, actual=equipo_actual: (
                    mover_usuario_equipo(c, ev.control.value) if ev.control.value and ev.control.value != actual else None),
            )
            detalle = []
            if ovs:
                detalle.append(ft.Text(f"{len(ovs)} OV · activa {ovs[0]}", size=10.5, color="#FBBF24"))
            if actividad.get("ultimo_mov"):
                detalle.append(ft.Text(str(actividad["ultimo_mov"])[:34], size=10, color=TEXT_MUTED))
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=10, vertical=7), border_radius=8, bgcolor="#1D2426",
                border=ft.Border.all(1, BORDER_COLOR),
                content=ft.Row([
                    ft.Container(width=28, height=28, border_radius=14, bgcolor="#334155", alignment=ft.Alignment.CENTER,
                                 content=ft.Text(nom[:1], size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE)),
                    ft.Column([ft.Text(nom, size=12, weight=ft.FontWeight.BOLD, color=TEXT_WHITE, max_lines=1,
                                       overflow=ft.TextOverflow.ELLIPSIS),
                               ft.Text(cod, size=10, color=ACCENT_CYAN), *detalle, menu],
                              spacing=3, tight=True, expand=True),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
            )

        def pintar_equipos(usuarios_lista: list, ovs_por_operador: dict, mapa_actividad: dict, ov_sin_asignar: dict):
            cajas = []
            for k, tit, desc, col, ico in EQUIPOS:
                miembros = [u for u in usuarios_lista
                            if (str(u.get("equipo_trabajo") or "").strip().upper() or "SIN_EQUIPO") == k]
                tarjetas = []
                for u in miembros:
                    cod = str(u.get("usuario") or "").strip().upper()
                    nom = str(u.get("nombre_completo") or cod).strip().upper()
                    tarjetas.append(tarjeta_usuario_equipo(
                        u, k, ovs_por_operador.get(cod, []) or ovs_por_operador.get(nom, []),
                        mapa_actividad.get(cod) or mapa_actividad.get(nom) or {}))
                esperando = ov_sin_asignar.get(k, 0)
                cajas.append(ft.Container(
                    col={"xs": 12, "sm": 6, "lg": 4, "xl": 2},
                    padding=10, border_radius=10, bgcolor=BG_CARD,
                    border=ft.Border(top=ft.BorderSide(3, col), left=ft.BorderSide(1, BORDER_COLOR),
                                     right=ft.BorderSide(1, BORDER_COLOR), bottom=ft.BorderSide(1, BORDER_COLOR)),
                    content=ft.Column([
                        ft.Row([ft.Icon(_ico(ico, "GROUPS_ROUNDED"), color=col, size=18),
                                ft.Text(tit, size=12.5, weight=ft.FontWeight.BOLD, color=TEXT_WHITE, expand=True),
                                ft.Container(padding=ft.Padding.symmetric(horizontal=8, vertical=2), border_radius=10,
                                             bgcolor=ft.Colors.with_opacity(0.18, col),
                                             content=ft.Text(str(len(miembros)), size=11, weight=ft.FontWeight.BOLD, color=col))],
                               spacing=6),
                        ft.Text(desc + (f" · {esperando} OV esperando" if esperando else ""), size=10.5,
                                color="#FBBF24" if esperando else TEXT_MUTED),
                        *(tarjetas or [ft.Container(padding=10, content=ft.Text("Sin usuarios", size=11, color=TEXT_MUTED))]),
                    ], spacing=6, tight=True),
                ))
            fila_equipos.controls = cajas

        def refrescar_monitor_usuarios_y_cola(e=None):
            bodega_act = obtener_bodega_activa(self.page)
            q_filtro = (txt_buscar_cola.value or "").strip().upper()

            try:
                res_u = supabase.table("wms_usuarios").select("*").order("id", desc=False).execute()
                usuarios_lista = [
                    u for u in (res_u.data or [])
                    if u.get("activo", True)
                    and (
                        coincide_bodega(u, bodega_act)
                        or "AMBAS" in str(u.get("bodega") or "").upper()
                        or "TODAS" in str(u.get("bodega") or "").upper()
                    )
                ]
                codigos_operadores = [str(u.get("usuario") or "").strip().upper() for u in usuarios_lista if u.get("usuario")]

                mapa_actividad_usr = {}
                movs_totales = 0
                try:
                    res_h = supabase.table("historial_movimientos").select("*").order("id", desc=True).limit(300).execute()
                    for m in (res_h.data or []):
                        if not coincide_bodega(m, bodega_act):
                            continue
                        movs_totales += 1
                        usr_k = str(m.get("usuario") or "APP_RF").strip().upper()
                        if usr_k not in mapa_actividad_usr:
                            mapa_actividad_usr[usr_k] = {
                                "ultimo_mov": f"{m.get('tipo_movimiento', 'MOV')} • SKU {m.get('sku', '-')}",
                                "conteo": 0,
                                "unidades": 0,
                            }
                        mapa_actividad_usr[usr_k]["conteo"] += 1
                        mapa_actividad_usr[usr_k]["unidades"] += int(float(m.get("unidades_afectadas") or 0))
                except Exception:
                    pass

                res_ov = supabase.table("netsuite_ordenes_venta").select("*").order("id", desc=False).limit(400).execute()
                ovs_por_operador = {}
                ov_sin_asignar = {}
                filas_cola = []
                ovs_vistas = set()
                cnt_pend_pick = 0
                cnt_pend_pack = 0

                for r in (res_ov.data or []):
                    if not coincide_bodega(r, bodega_act):
                        continue
                    ov_raw = str(r.get("numero_ov") or "").strip().upper()
                    ov_base = ov_raw.removesuffix("-FA").strip()
                    if not ov_base or ov_base in ovs_vistas:
                        continue

                    est_ov = str(r.get("estado_ns") or r.get("estado") or "PENDIENTE_PICKING").strip().upper()
                    if est_ov in ("PENDIENTE_FACTURACION", "FACTURADO", "EMPACADO", "COMPLETADO", "DESPACHADO", "ANULADO"):
                        continue

                    ovs_vistas.add(ov_base)
                    op_asig = str(r.get("operador_asignado") or "SIN ASIGNAR").strip().upper() or "SIN ASIGNAR"
                    if est_ov in ("PENDIENTE_PICKING", "PENDIENTE") and op_asig == "SIN ASIGNAR":
                        tipo_ov = ("FARMACIA" if (ov_raw.endswith("-FA") or ov_raw.startswith("OT-")
                                                  or "FARM" in str(r.get("canal_venta") or "").upper()) else "PICKING")
                        ov_sin_asignar[tipo_ov] = ov_sin_asignar.get(tipo_ov, 0) + 1
                    if est_ov == "PENDIENTE_PACKING":
                        cnt_pend_pack += 1
                    else:
                        cnt_pend_pick += 1
                        if op_asig and op_asig != "SIN ASIGNAR":
                            ovs_por_operador.setdefault(op_asig, []).append(ov_raw)

                    cli_str = str(r.get("cliente_nombre") or r.get("cliente") or "CLIENTE").strip()
                    canal_str = str(r.get("canal_venta") or "").upper()
                    es_fa = ov_raw.endswith("-FA") or "FARM" in canal_str or ov_raw.startswith("OT-")
                    fecha_s = str(r.get("fecha_emision_ns") or r.get("created_at") or "")[:10]

                    if q_filtro and not any(q_filtro in x for x in (ov_raw, cli_str.upper(), op_asig)):
                        continue

                    badge_canal = (
                        crear_badge_estado("FARMACIA (-FA)", "#92400E", "#FEF3C7")
                        if es_fa
                        else crear_badge_estado("OV NORMAL", "#1E3A8A", "#DBEAFE")
                    )
                    badge_etapa = (
                        crear_badge_estado("EN PACKING", "#0369A1", "#E0F2FE")
                        if est_ov == "PENDIENTE_PACKING"
                        else crear_badge_estado("EN COLA PICKING", "#92400E", "#FEF3C7")
                    )

                    opciones_dd = [ft.DropdownOption(key="SIN ASIGNAR", text="SIN ASIGNAR")] + [
                        ft.DropdownOption(key=op_c, text=f"👤 {op_c}") for op_c in codigos_operadores
                    ]
                    val_dd = op_asig if op_asig in codigos_operadores else "SIN ASIGNAR"

                    dd_op_fila = ft.Dropdown(
                        width=175,
                        dense=True,
                        value=val_dd,
                        bgcolor=BG_INPUT,
                        border_color=ACCENT_CYAN if val_dd != "SIN ASIGNAR" else BORDER_COLOR,
                        text_style=ft.TextStyle(size=11, color=TEXT_WHITE, weight=ft.FontWeight.BOLD),
                        content_padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                        options=opciones_dd,
                        on_select=lambda ev, id_o=r.get("id"), n_ov=ov_raw: asignar_operador_manual_ov(id_o, n_ov, ev.control.value),
                    )

                    filas_cola.append(
                        ft.DataRow(
                            color="#2A2419" if es_fa else None,
                            cells=[
                                ft.DataCell(ft.Text("ALTA (-FA)" if es_fa else "NORMAL", weight=ft.FontWeight.BOLD, size=10.5, color="#FBBF24" if es_fa else "#A78BFA")),
                                ft.DataCell(ft.Text(ov_raw, weight=ft.FontWeight.W_900, size=11.5, color="#FBBF24" if es_fa else ACCENT_CYAN)),
                                ft.DataCell(badge_canal),
                                ft.DataCell(ft.Text(fecha_s, size=11, color="#34D399")),
                                ft.DataCell(ft.Text(cli_str[:30], size=11, color=TEXT_WHITE)),
                                ft.DataCell(badge_etapa),
                                ft.DataCell(dd_op_fila),
                                ft.DataCell(
                                    ft.IconButton(icon=ft.Icons.BLOCK_ROUNDED, icon_size=18, icon_color="#F87171",
                                                  tooltip="Anular esta orden (solo administradores, sin nada pickeado)",
                                                  on_click=lambda e, id_o=r.get("id"), n_ov=ov_raw, c=cli_str: abrir_anular_ov(id_o, n_ov, c))
                                    if es_admin_pc() and est_ov in ("PENDIENTE_PICKING", "PENDIENTE") else ft.Text("")),
                            ],
                        )
                    )

                filas_u = []
                for u in usuarios_lista:
                    cod_u = str(u.get("usuario") or "").strip().upper()
                    nom_u = str(u.get("nombre_completo") or cod_u).strip().upper()
                    rol_u = str(u.get("rol") or "OPERADOR").strip().upper()
                    bod_u = str(u.get("bodega") or bodega_act).strip()

                    if q_filtro and not any(q_filtro in x for x in (cod_u, nom_u, rol_u)):
                        continue

                    inf_act = mapa_actividad_usr.get(cod_u) or mapa_actividad_usr.get(nom_u) or {}
                    cnt_m = inf_act.get("conteo", 0)
                    unid_m = inf_act.get("unidades", 0)
                    ult_txt = inf_act.get("ultimo_mov", "EN LÍNEA / DISPONIBLE")

                    cola_op = ovs_por_operador.get(cod_u, [])
                    if cola_op:
                        txt_ov_activa = f"Activa: {cola_op[0]}" + (f" (+{len(cola_op)-1} en cola)" if len(cola_op) > 1 else "")
                        badge_ov_op = crear_badge_estado(txt_ov_activa, "#065F46", "#D1FAE5")
                    else:
                        badge_ov_op = crear_badge_estado("SIN OV ASIGNADA", "#475569", "#1E293B")

                    filas_u.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(f"{nom_u} ({cod_u})", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(rol_u, size=10.5, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(bod_u, size=10.5, color="#34D399")),
                                ft.DataCell(badge_ov_op),
                                ft.DataCell(ft.Text(ult_txt[:36], size=10.5, color="#FBBF24")),
                                ft.DataCell(ft.Text(f"{cnt_m} movs", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(f"{unid_m} UN", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                            ]
                        )
                    )

                tabla_usuarios_rf.rows = filas_u
                tabla_cola_picking.rows = filas_cola
                try:
                    pintar_sesiones()
                except Exception as ex_s:
                    print(f"[WARN] Sesiones RF: {ex_s}")
                try:
                    pintar_equipos(usuarios_lista, ovs_por_operador, mapa_actividad_usr, ov_sin_asignar)
                except Exception as ex_eq:
                    # Un error en el tablero de equipos no debe dejar en blanco el resto del monitor
                    print(f"[WARN] Equipos de trabajo: {ex_eq}")
                    fila_equipos.controls = [ft.Text(f"No se pudo dibujar los equipos: {ex_eq}", size=11, color="#F87171")]
                lbl_kpi_usr_activos.value = str(len(usuarios_lista))
                lbl_kpi_cola_pend.value = str(cnt_pend_pick)
                lbl_kpi_en_pack.value = str(cnt_pend_pack)
                lbl_kpi_movs_hoy.value = str(movs_totales)
                self.page.update()
            except Exception as ex:
                print(f"[WARN] Error refrescando Monitor Usuarios y Cola: {ex}")
                registrar_error_pc("MONITOR_USUARIOS", f"{type(ex).__name__}: {ex}", traceback.format_exc())
                notificar_global(self.page, f"Monitor de usuarios: {ex}", "#B91C1C")

        txt_buscar_cola.on_change = refrescar_monitor_usuarios_y_cola

        barra_superior = ft.Container(
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            bgcolor="#222A2C",
            border_radius=8,
            border=ft.Border.all(1, BORDER_COLOR),
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(_ico("PRECISION_MANUFACTURING_OUTLINED", "HUB_OUTLINED"), color=ACCENT_CYAN, size=22),
                            ft.Text(
                                "MONITOR DE USUARIOS RF & ASIGNACIÓN AUTOMÁTICA DE COLA PICKING",
                                size=14.5,
                                weight=ft.FontWeight.W_900,
                                color=TEXT_WHITE,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Row(
                        [
                            txt_buscar_cola,
                            boton_primario(
                                "CARGAR OV A LOS EQUIPOS",
                                _ico("BOLT_ROUNDED", "SEND_ROUNDED"),
                                auto_asignar_todas_las_ovs_en_cola,
                                "#047857",
                                height_val=34,
                            ),
                            boton_primario(
                                "ACTUALIZAR EN VIVO",
                                _ico("SYNC_ROUNDED", "REFRESH_ROUNDED"),
                                refrescar_monitor_usuarios_y_cola,
                                ACCENT_BLUE,
                                height_val=34,
                            ),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                wrap=True,
            ),
        )

        fila_kpis = ft.Row(
            [
                caja_kpi(lbl_kpi_usr_activos, "Operadores Activos", "#10B981"),
                caja_kpi(lbl_kpi_cola_pend, "OVs en Cola Picking", "#F59E0B"),
                caja_kpi(lbl_kpi_en_pack, "OVs en Packing", ACCENT_CYAN),
                caja_kpi(lbl_kpi_movs_hoy, "Movimientos RF", "#8B5CF6"),
            ],
            spacing=12,
            wrap=True,
        )

        tarjeta_usuarios = ft.Container(
            padding=12,
            bgcolor=BG_CARD,
            border_radius=8,
            border=ft.Border.all(1, BORDER_COLOR),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(_ico("CENTER_FOCUS_STRONG_OUTLINED", "PERSON_SEARCH_OUTLINED"), color=ACCENT_CYAN, size=18),
                            ft.Text("1. MONITOR DE OPERADORES RF / PC Y OV ASIGNADA EN PISO", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                        ],
                        spacing=8,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=2),
                    cont_tabla_usuarios,
                ],
                spacing=8,
            ),
        )

        tarjeta_cola = ft.Container(
            padding=12,
            bgcolor=BG_CARD,
            border_radius=8,
            border=ft.Border.all(1, BORDER_COLOR),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(_ico("ALL_INBOX_OUTLINED", "INVENTORY_2_OUTLINED"), color="#FBBF24", size=18),
                            ft.Text("2. COLA ACTIVA DE PICKING Y ASIGNACIÓN DE OPERADOR (NORMAL VS FARMACIA -FA)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                        ],
                        spacing=8,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=2),
                    cont_tabla_cola,
                ],
                spacing=8,
            ),
        )

        tarjeta_equipos = ft.Container(
            padding=12,
            bgcolor="#202829",
            border_radius=8,
            border=ft.Border.all(1, BORDER_COLOR),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(_ico("GROUPS_ROUNDED", "PEOPLE_OUTLINE"), color=ACCENT_CYAN, size=18),
                            ft.Text("EQUIPOS DE TRABAJO", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            ft.Text("Elija el equipo de cada usuario en su tarjeta y luego presione CARGAR OV A LOS EQUIPOS. "
                                    "Generar olas ya no asigna operador.", size=11, color=TEXT_MUTED, expand=True),
                        ],
                        spacing=8,
                    ),
                    fila_equipos,
                ],
                spacing=10,
            ),
        )

        tarjeta_sesiones = ft.Container(
            padding=12,
            bgcolor=BG_CARD,
            border_radius=8,
            border=ft.Border.all(1, BORDER_COLOR),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(_ico("PHONELINK_LOCK_ROUNDED", "LOCK_OUTLINE"), color="#34D399", size=18),
                            ft.Text("SESIONES DEL CELULAR (ÚLTIMAS 24 H)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                            lbl_modo_sesion,
                        ],
                        spacing=8,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=2),
                    cont_tabla_sesiones,
                ],
                spacing=8,
            ),
        )

        self.sub_completo = ft.Column([fila_kpis, tarjeta_equipos, tarjeta_usuarios, tarjeta_sesiones, tarjeta_cola], spacing=10)
        self.sub_solo_cola = ft.Column([fila_kpis, tarjeta_cola], spacing=10)
        self.sub_solo_usuarios = ft.Column([fila_kpis, tarjeta_equipos, tarjeta_usuarios, tarjeta_sesiones], spacing=10)
        self.contenedor = ft.Container(content=self.sub_completo)

        self.vista = ft.Container(
            padding=12,
            bgcolor=BG_MODULO,
            expand=True,
            content=ft.Column([barra_superior, self.contenedor], spacing=10, scroll=ft.ScrollMode.ALWAYS, expand=True),
        )
        self.refrescar_func = refrescar_monitor_usuarios_y_cola

    def refrescar(self, e=None):
        self.refrescar_func(e)

    def sel_sub_monitor(self, idx: int):
        vistas = [self.sub_completo, self.sub_solo_cola, self.sub_solo_usuarios]
        self.contenedor.content = vistas[idx if 0 <= idx < len(vistas) else 0]
        self.refrescar_func()
        self.page.update()


def main(page: ft.Page):
    page.title = "LUDIPEK WMS | Cloud Planning"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.window.maximized = True
    page.overlay.clear()
    page.bodega_actual = "Bodega Santiago"

    txt_login_user = ft.TextField(label="Usuario / RUT", width=300, prefix_icon=ft.Icons.PERSON)
    txt_login_pass = ft.TextField(
        label="Contraseña",
        width=300,
        password=True,
        can_reveal_password=True,
        prefix_icon=ft.Icons.LOCK,
    )
    dd_login_bodega = ft.Dropdown(
        label="Bodega a Operar",
        width=300,
        value="Bodega Santiago",
        options=[
            ft.DropdownOption(key="Bodega Santiago", text="Bodega Santiago (CD Central)"),
            ft.DropdownOption(key="Bodega Concepcion", text="Bodega Concepción (CCP)"),
        ],
    )
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
            fila_u = None
            try:
                # Validación en el servidor (acepta contraseñas cifradas bcrypt y las antiguas en texto)
                res = supabase.rpc("wms_login", {"p_usuario": user_val, "p_password": pass_val}).execute()
                fila_u = res.data if isinstance(res.data, dict) else None
                if fila_u and fila_u.get("error") == "USUARIO_INACTIVO":
                    lbl_login_error.value = "Usuario inactivo. Contacte a Gerencia."
                    page.update()
                    return
            except Exception as ex_rpc:
                # Respaldo mientras no se ejecute sql/robustez_2026_11/04_funciones_operacion.sql
                print(f"[WARN] wms_login no disponible, se usa validación local: {ex_rpc}")
                user_patron = user_val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                res = supabase.table("wms_usuarios").select("*").ilike("usuario", user_patron).limit(1).execute()
                fila_tmp = res.data[0] if res.data else None
                if fila_tmp and fila_tmp.get("activo") and verificar_password_seguro(pass_val, fila_tmp.get("password", "")):
                    fila_u = fila_tmp

            if fila_u:
                rol_usr = str(fila_u.get("rol") or "OPERADOR").strip().upper()
                bodega_asignada = str(fila_u.get("bodega") or "Bodega Santiago").strip()
                bodega_elegida = str(dd_login_bodega.value or bodega_asignada).strip()

                tiene_acceso_global = (
                    "ADMIN" in rol_usr
                    or "AMBAS" in bodega_asignada.upper()
                    or "TODAS" in bodega_asignada.upper()
                )

                if not tiene_acceso_global and bodega_asignada.upper() != bodega_elegida.upper():
                    lbl_login_error.value = (
                        f"Acceso denegado: Tu usuario pertenece exclusivamente a {bodega_asignada}."
                    )
                    page.update()
                    return

                intentos_fallidos = 0
                page.usuario_actual = fila_u.get("nombre_completo") or user_val
                page.rol_actual = rol_usr
                page.bodega_actual = bodega_elegida if tiene_acceso_global else bodega_asignada
                page.tiene_acceso_multibodega = tiene_acceso_global
                fijar_contexto_errores_pc(page.usuario_actual, page.bodega_actual)

                mod_pc_str = ",".join(lista_permisos(fila_u.get("modulos_pc") or fila_u.get("permisos_pc")))
                if not mod_pc_str and os.path.exists("config_permisos_wms.json"):
                    try:
                        import json
                        with open("config_permisos_wms.json", "r", encoding="utf-8") as f_p:
                            mapa_p = json.load(f_p)
                        if user_val in mapa_p:
                            mod_pc_str = ",".join(mapa_p[user_val].get("modulos_pc", []))
                    except Exception:
                        pass

                page.modulos_pc_usuario = mod_pc_str
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

    txt_login_user.on_submit = intentar_login
    txt_login_pass.on_submit = intentar_login

    pantalla_login = ft.Container(
        expand=True,
        alignment=ft.Alignment.CENTER,
        bgcolor="#292526",
        content=ft.Container(
            padding=40,
            width=400,
            bgcolor=ft.Colors.WHITE,
            border_radius=16,
            shadow=ft.BoxShadow(blur_radius=30, color="#73000000", spread_radius=5, offset=ft.Offset(0, 10)),
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.ACCOUNT_CIRCLE_ROUNDED, size=80, color="#507572"),
                    ft.Text("INICIAR SESIÓN", size=24, weight=ft.FontWeight.W_900, color="#273132"),
                    ft.Text("LUDIPEK WMS CLOUD", size=12, color="#64748B", weight=ft.FontWeight.BOLD),
                    ft.Divider(height=18, color="transparent"),
                    txt_login_user,
                    txt_login_pass,
                    dd_login_bodega,
                    lbl_login_error,
                    ft.Divider(height=10, color="transparent"),
                    ft.Button(
                        content=ft.Text("INGRESAR A WMS", weight=ft.FontWeight.BOLD),
                        bgcolor="#507572",
                        color=ft.Colors.WHITE,
                        width=300,
                        height=48,
                        on_click=intentar_login,
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
                spacing=10,
            ),
        ),
    )

    page.bgcolor = "#292526"
    page.add(pantalla_login)

    def iniciar_torre_de_control():
        tarjetas_adaptables = []
        kpis_adaptables = []
        indice_modulo_activo = -1
        indice_submodulo_activo = 0
        menu_contraido_manual = False
        sesion_activa = True
        historial_recientes = []

        def get_indice_activo():
            return indice_modulo_activo

        def wrapper_activar(mod, sub=0):
            activar_modulo_principal(mod, sub)

        idx_ini_tablas = len(TABLAS_SCROLL_ADAPTABLES)

        dash = m0_dashboard.DashboardModulo(page, tarjetas_adaptables, kpis_adaptables, wrapper_activar)
        recep = m1_recepcion.RecepcionModulo(page, tarjetas_adaptables, kpis_adaptables, get_indice_activo)
        puta = m2_putaway.PutawayModulo(page, tarjetas_adaptables, kpis_adaptables)
        pick = m3_picking.PickingModulo(page, tarjetas_adaptables, kpis_adaptables)
        mon_cola = MonitorUsuariosColaModulo(page, tarjetas_adaptables, kpis_adaptables)
        inv = m4_inventario.InventarioModulo(page, tarjetas_adaptables, kpis_adaptables)
        mae = m5_maestra.MaestraModulo(page, tarjetas_adaptables, kpis_adaptables)
        imp = m6_impresion.ImpresionModulo(page, tarjetas_adaptables, kpis_adaptables)
        ruteo = m7_ruteo_facturacion.RuteoFacturacionModulo(page, tarjetas_adaptables, kpis_adaptables)
        bodega_sesion_normalizada = str(getattr(page, "bodega_actual", "") or "").upper().replace("Ó", "O")
        es_bodega_concepcion = "CONCEPCION" in bodega_sesion_normalizada
        recep_ccp = (
            m8_recepcion_ccp.RecepcionTrasladosCcpModulo(page, tarjetas_adaptables, kpis_adaptables)
            if es_bodega_concepcion
            else None
        )

        tablas_scroll_sesion = list(TABLAS_SCROLL_ADAPTABLES[idx_ini_tablas:])
        del TABLAS_SCROLL_ADAPTABLES[idx_ini_tablas:]

        vistas_mapa = [
            (
                "Dashboards",
                _ico("TOKEN_OUTLINED", "HEXAGON_OUTLINED", "DASHBOARD_OUTLINED"),
                dash.vista,
                dash.refrescar_dashboard,
                dash.sel_sub_dash,
                [
                    ("1. Resumen operativo", _ico("VIEW_IN_AR_OUTLINED", "DASHBOARD_OUTLINED")),
                    ("2. Flujo y productividad", _ico("PRECISION_MANUFACTURING_OUTLINED", "BOLT_ROUNDED")),
                    ("3. Inventario y vencimientos", _ico("CATEGORY_OUTLINED", "PIE_CHART_OUTLINE_ROUNDED")),
                ],
            ),
            (
                "Recepción\n(Ingresos PO)",
                _ico("ALL_INBOX_OUTLINED", "INVENTORY_2_OUTLINED"),
                recep.vista,
                recep.cargar_lista_asns,
                recep.sel_sub_inb,
                [
                    ("Recepción y validación", _ico("FACT_CHECK_OUTLINED", "INVENTORY_2_OUTLINED")),
                    ("Indicadores", _ico("INSIGHTS_ROUNDED", "BAR_CHART_ROUNDED")),
                    ("Historial", _ico("MANAGE_SEARCH_ROUNDED", "QR_CODE_SCANNER_OUTLINED")),
                    ("Control de calidad", _ico("VERIFIED_USER_OUTLINED", "CENTER_FOCUS_STRONG_OUTLINED")),
                    ("Ajustes de OC y pallets", _ico("EDIT_NOTE_ROUNDED", "CROP_FREE_OUTLINED")),
                ],
            ),
            (
                "Almacenamiento\n(Mov. LPN)",
                _ico("VIEW_IN_AR_OUTLINED", "WIDGETS_OUTLINED"),
                puta.vista,
                puta.cargar_inventario_ubicaciones,
                puta.sel_sub_put,
                [
                    ("Mapa de racks", _ico("VIEW_COLUMN_OUTLINED", "DOMAIN_OUTLINED")),
                    ("Reabastecimiento", _ico("ARROW_DOWNWARD_ROUNDED", "INVENTORY_2_OUTLINED")),
                    ("Buscar pallet o ubicación", _ico("MANAGE_SEARCH_ROUNDED", "SEARCH_ROUNDED")),
                    ("Gemelo digital 3D", _ico("VIEW_IN_AR_ROUNDED", "TOKEN_OUTLINED")),
                ],
            ),
            (
                "Olas\n(Packing)",
                _ico("INVENTORY_2_OUTLINED", "VIEW_IN_AR_OUTLINED"),
                pick.vista,
                pick.cargar_monitor_packing_dual,
                pick.sel_sub_olas,
                [
                    ("1. Resumen Operativo", _ico("DASHBOARD_OUTLINED", "VIEW_QUILT_OUTLINED")),
                    ("2. Crear / Liberar Olas", _ico("ALL_INBOX_OUTLINED", "CLOUD_DOWNLOAD_OUTLINED")),
                    ("3. Seguimiento Picking / Packing", _ico("FACT_CHECK_OUTLINED", "INVENTORY_OUTLINED")),
                    ("4. Facturación NetSuite", _ico("CENTER_FOCUS_STRONG_OUTLINED", "RECEIPT_LONG_ROUNDED")),
                ],
            ),
            (
                "Monitor Usuarios\n& Cola Picking",
                _ico("PRECISION_MANUFACTURING_OUTLINED", "HUB_OUTLINED"),
                mon_cola.vista,
                mon_cola.refrescar,
                mon_cola.sel_sub_monitor,
                [
                    ("1. Monitor Operadores & Cola en Vivo", _ico("CENTER_FOCUS_STRONG_OUTLINED", "VISIBILITY_OUTLINED")),
                    ("2. Cola Activa de Picking", _ico("ALL_INBOX_OUTLINED", "INVENTORY_2_OUTLINED")),
                    ("3. Operadores y Rendimiento RF", _ico("PRECISION_MANUFACTURING_OUTLINED", "BOLT_ROUNDED")),
                ],
            ),
            (
                "Mov. Stock\n(Inventario)",
                _ico("CENTER_FOCUS_STRONG_OUTLINED", "LIBRARY_BOOKS_OUTLINED"),
                inv.vista,
                getattr(inv, "actualizar_todos_los_datos_func", None),
                inv.sel_sub_inventario,
                [
                    ("Consulta de stock", _ico("MANAGE_SEARCH_ROUNDED", "SEARCH_ROUNDED")),
                    ("Tareas de conteo", _ico("ASSIGNMENT_IND_OUTLINED", "CHECKLIST_ROUNDED")),
                    ("Resultados de conteo", _ico("FACT_CHECK_OUTLINED", "TRACK_CHANGES_ROUNDED")),
                    ("Conciliación WMS vs NetSuite", _ico("COMPARE_ARROWS_ROUNDED", "RULE_ROUNDED")),
                    ("Trazabilidad", _ico("HISTORY_ROUNDED", "QR_CODE_SCANNER")),
                    ("Alertas y desvíos", _ico("WARNING_AMBER_ROUNDED", "CROP_FREE")),
                ],
            ),
            (
                "Admin & Maestra\n(Usuarios / SKU)",
                _ico("CATEGORY_OUTLINED", "ADMIN_PANEL_SETTINGS_OUTLINED"),
                mae.vista,
                mae.cargar_maestra_skus,
                mae.sel_sub_maestra,
                [
                    ("1. Usuarios y Accesos (PC / RF)", _ico("CENTER_FOCUS_STRONG_OUTLINED", "MANAGE_ACCOUNTS_ROUNDED")),
                    ("2. Catálogo Maestro y Enrolamiento", _ico("INVENTORY_2_OUTLINED", "INVENTORY_2_ROUNDED")),
                ],
            ),
            (
                "Ruteo & Fact.\n(Drivin / SLA)",
                _ico("LOCAL_SHIPPING_OUTLINED", "ALL_INBOX_OUTLINED"),
                ruteo.vista,
                ruteo.cargar_datos_ruteo,
                ruteo.sel_sub_ruteo,
                [
                    ("1. Mesa Facturación & Cruce NS", _ico("RECEIPT_LONG_ROUNDED", "ALL_INBOX_OUTLINED")),
                    ("2. Ruteo Drivin & 24 Arenas", _ico("LOCAL_SHIPPING_OUTLINED", "INVENTORY_2_OUTLINED")),
                    ("3. Entregas & SLA 36h / 72h", _ico("CENTER_FOCUS_STRONG_OUTLINED", "VERIFIED_OUTLINED")),
                    ("4. Maestra de Flota & Camiones", _ico("PRECISION_MANUFACTURING_OUTLINED", "BADGE_OUTLINED")),
                ],
            ),
            (
                "Etiquetas\n(Impresión)",
                _ico("QR_CODE_SCANNER_OUTLINED", "QR_CODE_SCANNER", "QR_CODE_2_ROUNDED"),
                imp.vista,
                None,
                imp.sel_sub_imp,
                [
                    ("1. Imprimir LPN", _ico("QR_CODE_SCANNER_OUTLINED", "QR_CODE_2_ROUNDED")),
                    ("2. Ubicación / Tótem", _ico("CROP_FREE_OUTLINED", "CROP_FREE", "LOCATION_ON_OUTLINED")),
                    ("3. Etiquetas Cencosud", _ico("INVENTORY_2_OUTLINED", "LOCAL_MALL_OUTLINED")),
                    ("4. Etiquetas Mercado Libre", _ico("ALL_INBOX_OUTLINED", "LOCAL_SHIPPING_OUTLINED")),
                ],
            ),
        ]

        if es_bodega_concepcion and recep_ccp is not None:
            vistas_mapa.append(
                (
                    "Recepción Traslados\n(Concepción)",
                    _ico("MOVE_TO_INBOX_ROUNDED", "WAREHOUSE_ROUNDED"),
                    recep_ccp.vista,
                    recep_ccp.refrescar,
                    recep_ccp.sel_sub_recepcion_ccp,
                    [
                        ("En camino y recibiendo", _ico("LOCAL_SHIPPING_OUTLINED", "ALL_INBOX_OUTLINED")),
                        ("Recibidas y diferencias", _ico("FACT_CHECK_OUTLINED", "MOVE_TO_INBOX_ROUNDED")),
                    ],
                )
            )

        COLOR_BG_PORTAL = "#1B2122"
        COLOR_PANEL_IZQ = "#20282A"
        COLOR_HEADER = "#141A1B"

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

        breadcrumb_txt = ft.Text(
            "Inicio", size=11.5, color="#CBD5E1", weight=ft.FontWeight.W_600,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        barra_contexto = ft.Container(
            height=36,
            padding=ft.Padding.symmetric(horizontal=12, vertical=5),
            bgcolor="#202728",
            border=ft.Border(bottom=ft.BorderSide(1, "#3B484B")),
            content=ft.Row([
                ft.Icon(ft.Icons.ROUTE_ROUNDED, size=16, color="#38BDF8"),
                breadcrumb_txt,
            ], spacing=7),
        )

        def generar_menu_lateral(idx_mod: int, sub_activo: int = 0, compacto: bool = False):
            texto_mod, icono_mod, _, _, fn_sub, sub_items = vistas_mapa[idx_mod]
            items = []
            for s_idx, (txt_sub, ico_sub) in enumerate(sub_items):
                activo = s_idx == sub_activo
                def ir_submodulo(e, m=idx_mod, s=s_idx, fn=fn_sub):
                    nonlocal indice_submodulo_activo
                    cerrar_superficies_transitorias(page)
                    indice_submodulo_activo = s
                    registrar_visita_reciente(m, s)
                    if fn:
                        fn(s)
                    panel_submenus.content = generar_menu_lateral(m, s, panel_submenus.width <= 76)
                    breadcrumb_txt.value = f"{vistas_mapa[m][0].replace(chr(10), ' ')}  ›  {vistas_mapa[m][5][s][0]}"
                    page.update()
                items.append(
                    ft.Container(
                        bgcolor="#155E75" if activo else None,
                        border=ft.Border(left=ft.BorderSide(3, "#38BDF8" if activo else "transparent")),
                        border_radius=6,
                        tooltip=txt_sub,
                        content=ft.ListTile(
                            leading=ft.Icon(ico_sub, color="#E0F2FE" if activo else "#38BDF8", size=19),
                            title=None if compacto else ft.Text(txt_sub, size=11.5, color="#FFFFFF", weight=ft.FontWeight.BOLD if activo else ft.FontWeight.W_500),
                            on_click=ir_submodulo,
                            hover_color="#3F5657",
                            dense=True,
                        ),
                    )
                )
            return ft.Container(
                # mismo ancho que el panel que lo contiene (antes 215 fijo dentro de un panel de 190 en notebook)
                width=68 if compacto else (panel_submenus.width or 215),
                bgcolor="#2F3738",
                border=ft.Border(right=ft.BorderSide(1, "#3B484B")),
                content=ft.Column([
                    ft.Container(
                        padding=10 if compacto else 15,
                        bgcolor="#232A2B",
                        border=ft.Border(bottom=ft.BorderSide(1, "#3B484B")),
                        tooltip=texto_mod.replace("\n", " "),
                        content=ft.Row([
                            ft.Icon(icono_mod, color="#38BDF8", size=22),
                            *( [] if compacto else [ft.Text(texto_mod.replace("\n", " "), size=12.5, weight=ft.FontWeight.BOLD, color="#FFFFFF", expand=True)] ),
                        ], spacing=9),
                    ),
                    ft.Column(items, spacing=3, scroll=ft.ScrollMode.AUTO, expand=True),
                ], spacing=0, expand=True),
            )

        # Código de permiso de cada módulo. El orden DEBE coincidir con vistas_mapa (7 = Ruteo, 8 = Etiquetas).
        codigos_mod = [
            "PC_DASHBOARD",
            "PC_RECEPCION",
            "PC_ALMACENAMIENTO",
            "PC_OLAS",
            "PC_OLAS",
            "PC_INVENTARIO",
            "PC_ADMIN_MAESTRA",
            "PC_RUTEO",
            "PC_IMPRESION",
        ]
        if es_bodega_concepcion:
            codigos_mod.append("PC_RECEPCION_CCP")

        def modulo_permitido(idx_sel: int) -> bool:
            """Mismo criterio en el portal, el menú rápido y al abrir el módulo."""
            if idx_sel < 0 or idx_sel >= len(vistas_mapa):
                return False
            cod_req = codigos_mod[idx_sel] if idx_sel < len(codigos_mod) else "PC_RECEPCION_CCP"
            if cod_req == "PC_RECEPCION_CCP" and not es_bodega_concepcion:
                return False
            rol_usr = str(getattr(page, "rol_actual", "")).upper()
            permisos_set = {
                p.strip()
                for p in str(getattr(page, "modulos_pc_usuario", "") or "").upper().replace(";", ",").split(",")
                if p.strip()
            }
            # Comparación exacta por código. Sin permisos configurados = acceso completo (compatibilidad).
            return "ADMIN" in rol_usr or not permisos_set or cod_req in permisos_set

        def avisar_sin_permiso(e=None):
            notificar_global(page, "Tu perfil no tiene este módulo habilitado. Pide acceso a un administrador (Maestra → Usuarios).", "#B45309")

        def activar_modulo_principal(idx_sel: int, sub_idx: int = 0):
            nonlocal indice_modulo_activo, indice_submodulo_activo
            if idx_sel < 0 or idx_sel >= len(vistas_mapa):
                return
            if not modulo_permitido(idx_sel):
                avisar_sin_permiso()
                return

            cerrar_superficies_transitorias(page)
            indice_modulo_activo = idx_sel
            indice_submodulo_activo = sub_idx
            contenedor_vista_activa.content = ft.Container(
                alignment=ft.Alignment.CENTER,
                content=ft.ProgressRing(width=24, height=24, stroke_width=2, color="#38BDF8"),
            )
            registrar_visita_reciente(idx_sel, sub_idx)
            perfil_nav = obtener_perfil_responsive(page)
            panel_submenus.width = perfil_nav["menu_width"]
            panel_submenus.content = generar_menu_lateral(idx_sel, sub_idx, perfil_nav["compacto"])
            panel_submenus.visible = True
            vista_destino = vistas_mapa[idx_sel][2]
            aplicar_responsive_a_vista(vista_destino, obtener_perfil_responsive(page))
            contenedor_vista_activa.content = ft.Row(
                [vista_destino], alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.START, expand=True,
            )
            breadcrumb_txt.value = f"{vistas_mapa[idx_sel][0].replace(chr(10), ' ')}  ›  {vistas_mapa[idx_sel][5][sub_idx][0]}"
            accion_recarga = vistas_mapa[idx_sel][3]
            fn_sub = vistas_mapa[idx_sel][4]
            if fn_sub:
                fn_sub(sub_idx)
            if accion_recarga:
                accion_recarga()
            page.bgcolor = "#1B2122"
            btn_home.visible = True
            cuerpo_principal.content = ft.Row([
                panel_submenus,
                ft.Column([barra_contexto, contenedor_vista_activa], spacing=0, expand=True),
            ], expand=True, spacing=0)
            adaptar_resolucion_automatica()
            page.update()

        def volver_al_home(e=None):
            nonlocal indice_modulo_activo
            indice_modulo_activo = -1
            btn_home.visible = False
            page.bgcolor = COLOR_BG_PORTAL
            cargar_datos_vivos_panel_izquierdo()
            cargar_indicadores_portal()
            cuerpo_principal.content = vista_portal_home
            page.update()

        def toggle_menu_tres_rayas(e=None):
            if indice_modulo_activo == -1:
                panel_perfil.visible = not panel_perfil.visible
            else:
                panel_submenus.visible = not panel_submenus.visible
            page.update()

        DESCRIPCION_MODULOS = [
            "Indicadores y productividad",
            "Órdenes de compra, LPN y calidad",
            "Putaway y mapa de racks",
            "Picking, packing y facturación",
            "Operadores y cola de picking",
            "Stock, conteos y trazabilidad",
            "Usuarios y productos",
            "Facturación, rutas y SLA",
            "Etiquetas e impresión",
            "Recepción de traslados en CCP",
        ]
        botones_grid = []
        for idx, (texto_mod, icono_mod, _, _, _, _) in enumerate(vistas_mapa):
            permitido = modulo_permitido(idx)
            botones_grid.append(
                ft.Container(
                    width=230, height=112,
                    padding=16,
                    bgcolor="#232B2D" if permitido else "#1D2426",
                    border=ft.Border.all(1, "#334044" if permitido else "#2A3335"),
                    border_radius=12,
                    ink=permitido,
                    on_click=(lambda e, i=idx: activar_modulo_principal(i)) if permitido else avisar_sin_permiso,
                    tooltip=None if permitido else "No habilitado en tu perfil",
                    # Sin permiso: se ve apagado, con candado, y no abre el módulo
                    opacity=1.0 if permitido else 0.45,
                    content=ft.Column([
                        ft.Row([
                            ft.Container(
                                width=40, height=40, border_radius=10,
                                bgcolor=ft.Colors.with_opacity(0.15, "#38BDF8" if permitido else "#64748B"),
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(icono_mod, size=22, color="#38BDF8" if permitido else "#64748B"),
                            ),
                            ft.Icon(ft.Icons.LOCK_ROUNDED if not permitido else ft.Icons.ARROW_FORWARD_ROUNDED,
                                    size=18, color="#64748B"),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Text(texto_mod.replace("\n", " "), size=14, weight=ft.FontWeight.W_600,
                                color="#F1F5F9" if permitido else "#94A3B8", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(DESCRIPCION_MODULOS[idx] if idx < len(DESCRIPCION_MODULOS) else "",
                                size=11.5, color="#94A3B8", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=6, tight=True),
                )
            )

        usuario_logueado = getattr(page, "usuario_actual", "Operador")
        rol_logueado = getattr(page, "rol_actual", "Administrador WMS")

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

        tiene_gif_gato = os.path.exists(os.path.join("assets", "cat_walk_loop.gif"))
        tiene_sprites_gato = os.path.exists(os.path.join("assets", "cat_walk_0.png"))
        src_caminata_gato = "/cat_walk_loop.gif" if tiene_gif_gato else ("/cat_walk_0.png" if tiene_sprites_gato else "/logo.png")

        img_gato_realista = ft.Image(
            src=src_caminata_gato,
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

        def dormir_interrumpible(segundos: float) -> bool:
            pasos = max(1, int(segundos / 0.1))
            for _ in range(pasos):
                if not sesion_activa or indice_modulo_activo != -1:
                    return False
                time.sleep(0.1)
            return True

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
                ya_saludo = False
                tiene_sprites_izq = os.path.exists(os.path.join("assets", "cat_walk_left_0.png"))

                # 1. CAMINATA DE IDA (IZQUIERDA -> DERECHA)
                for pos_x in range(0, ancho_max + 1, 8):
                    if not sesion_activa or indice_modulo_activo != -1:
                        break

                    paso += 1
                    actor_gato.margin = ft.Margin.only(left=pos_x)

                    if tiene_sprites_gato:
                        img_gato_realista.src = f"/cat_walk_{paso % 6}.png"

                    # Detenerse a la mitad para sentarse y mostrar el saludo
                    if not ya_saludo and abs(pos_x - mitad) <= 8:
                        ya_saludo = True
                        if os.path.exists(os.path.join("assets", "cat_sit.png")):
                            img_gato_realista.src = "/cat_sit.png"
                        burbuja_miau.visible = True
                        page.update()

                        if not dormir_interrumpible(2.6):
                            break

                        burbuja_miau.visible = False
                    else:
                        page.update()
                        time.sleep(0.06)

                # 2. DAR LA VUELTA Y CAMINAR DE REGRESO (DERECHA -> IZQUIERDA)
                if sesion_activa and indice_modulo_activo == -1:
                    time.sleep(0.25)
                    for pos_x in range(ancho_max, -1, -8):
                        if not sesion_activa or indice_modulo_activo != -1:
                            break

                        paso += 1
                        actor_gato.margin = ft.Margin.only(left=pos_x)

                        if tiene_sprites_izq:
                            img_gato_realista.src = f"/cat_walk_left_{paso % 6}.png"
                        elif tiene_sprites_gato:
                            img_gato_realista.src = f"/cat_walk_{paso % 6}.png"

                        page.update()
                        time.sleep(0.06)

                # Al terminar el recorrido de regreso, quedar sentado en su lugar inicial
                if sesion_activa and indice_modulo_activo == -1:
                    actor_gato.margin = ft.Margin.only(left=0)
                    if os.path.exists(os.path.join("assets", "cat_sit.png")):
                        img_gato_realista.src = "/cat_sit.png"
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
                for _ in range(48):
                    if not sesion_activa:
                        break
                    time.sleep(0.5)

        tab_activa_izq = "ACTIVITY"
        lbl_estado_proceso = ft.Text(
            "Cargando actividad de la bodega…",
            size=12,
            color="#E2E8F0",
        )
        txt_badge_anuncios = ft.Text("0", color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, size=11)
        col_contenido_tab_izq = ft.Column(spacing=6)
        col_lista_anuncios = ft.Column(spacing=6, visible=True)

        btn_tab_activity = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=6,
            bgcolor="#155E75",
            ink=True,
            content=ft.Text("Actividad", color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, size=12),
        )
        btn_tab_recent = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=6,
            bgcolor="transparent",
            ink=True,
            content=ft.Text("Recientes", color="#94A3B8", weight=ft.FontWeight.W_500, size=12),
        )
        btn_tab_favorites = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=6,
            bgcolor="transparent",
            ink=True,
            content=ft.Text("Favoritos", color="#94A3B8", weight=ft.FontWeight.W_500, size=12),
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
                bodega_act = str(getattr(page, "bodega_actual", "Bodega Santiago") or "Bodega Santiago").strip()
                res_pos = supabase.table("asn_cabecera").select("*").neq("estado", "COMPLETADO").order("id", desc=True).limit(15).execute()
                pos_activas = [
                    r for r in (res_pos.data or [])
                    if not r.get("bodega") or str(r.get("bodega")).strip().upper() == bodega_act.upper()
                ][:5]

                res_lpns = supabase.table("registro_recepcion").select("*").order("id", desc=True).limit(15).execute()
                ultimos_lpns = [
                    r for r in (res_lpns.data or [])
                    if not r.get("bodega") or str(r.get("bodega")).strip().upper() == bodega_act.upper()
                ][:5]

                lbl_estado_proceso.value = (
                    f"{bodega_act} • {len(pos_activas)} POs en curso y {len(ultimos_lpns)} LPNs recientes."
                )

                anuncios_items = []
                if pos_activas:
                    po_top = pos_activas[0]
                    cod_top = po_top.get("numero_oc") or po_top.get("codigo_asn") or "PO"
                    anuncios_items.append(
                        crear_item_panel_izq(
                            _ico("ALL_INBOX_OUTLINED", "LOCAL_SHIPPING_OUTLINED"),
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
                            lambda ev: activar_modulo_principal(1, 3),
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

                col_contenido_tab_izq.controls.clear()
                if tab_activa_izq == "ACTIVITY":
                    if ultimos_lpns:
                        for r in ultimos_lpns[:3]:
                            col_contenido_tab_izq.controls.append(
                                crear_item_panel_izq(
                                    _ico("QR_CODE_SCANNER_OUTLINED", "QR_CODE_2_ROUNDED"),
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
                        (_ico("ALL_INBOX_OUTLINED", "FACT_CHECK_OUTLINED"), "Recepción 3-Way Match", "Conciliar PO vs Andén RF", 1, 0),
                        (_ico("TOKEN_OUTLINED", "VIEW_IN_AR_ROUNDED"), "Gemelo Digital 3D", "Mapa interactivo de Racks", 2, 3),
                        (_ico("PRECISION_MANUFACTURING_OUTLINED", "HUB_OUTLINED"), "Monitor Usuarios & Cola", "Operadores y OVs en vivo", 4, 0),
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
                btn_t.bgcolor = "#155E75" if activo else "transparent"
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
                            ft.Text("Resumen de bodega", size=17, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
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
                                ft.Text("Avisos", color=ft.Colors.WHITE, size=13, weight=ft.FontWeight.BOLD, expand=True),
                                ft.Icon(ft.Icons.EXPAND_MORE_ROUNDED, color="#94A3B8", size=18),
                            ],
                            spacing=8,
                        ),
                    ),
                    col_lista_anuncios,
                ],
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            )
        )

        hora_actual_saludo = datetime.now().hour
        saludo = "Buenos días" if hora_actual_saludo < 12 else ("Buenas tardes" if hora_actual_saludo < 20 else "Buenas noches")
        nombre_saludo = str(getattr(page, "nombre_usuario", "") or usuario_logueado).split(" ")[0].capitalize()
        DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        hoy_dt = datetime.now()
        fecha_larga = f"{DIAS_ES[hoy_dt.weekday()].capitalize()} {hoy_dt.day} de {MESES_ES[hoy_dt.month - 1]}"

        def tarjeta_indicador_portal(lbl_valor: ft.Text, etiqueta: str, color: str, destino: tuple):
            permitido = modulo_permitido(destino[0])
            return ft.Container(
                col={"xs": 6, "md": 3},
                padding=14, border_radius=12, bgcolor="#232B2D",
                border=ft.Border(left=ft.BorderSide(3, color), top=ft.BorderSide(1, "#334044"),
                                 right=ft.BorderSide(1, "#334044"), bottom=ft.BorderSide(1, "#334044")),
                ink=permitido,
                on_click=(lambda e: activar_modulo_principal(*destino)) if permitido else None,
                content=ft.Column([lbl_valor, ft.Text(etiqueta, size=12, color="#94A3B8")], spacing=2, tight=True),
            )

        lbl_portal_recep = ft.Text("—", size=24, weight=ft.FontWeight.W_700, color="#F1F5F9")
        lbl_portal_picking = ft.Text("—", size=24, weight=ft.FontWeight.W_700, color="#F1F5F9")
        lbl_portal_packing = ft.Text("—", size=24, weight=ft.FontWeight.W_700, color="#F1F5F9")
        lbl_portal_fact = ft.Text("—", size=24, weight=ft.FontWeight.W_700, color="#F1F5F9")

        def cargar_indicadores_portal():
            try:
                bodega_act = str(getattr(page, "bodega_actual", "Bodega Santiago") or "Bodega Santiago")
                filas = supabase.table("netsuite_ordenes_venta").select("estado_ns, bodega").order("id", desc=True).limit(800).execute().data or []
                cuenta = {}
                for f in filas:
                    if str(f.get("bodega") or "Bodega Santiago") != bodega_act:
                        continue
                    est = str(f.get("estado_ns") or "PENDIENTE_PICKING").upper()
                    cuenta[est] = cuenta.get(est, 0) + 1
                lbl_portal_picking.value = str(cuenta.get("PENDIENTE_PICKING", 0) + cuenta.get("PICKING_EN_PROCESO", 0) + cuenta.get("PENDIENTE", 0))
                lbl_portal_packing.value = str(cuenta.get("PENDIENTE_PACKING", 0) + cuenta.get("PACKING_EN_PROCESO", 0))
                lbl_portal_fact.value = str(cuenta.get("PENDIENTE_FACTURACION", 0))
                asn = supabase.table("asn_cabecera").select("estado, bodega").neq("estado", "COMPLETADO").limit(300).execute().data or []
                lbl_portal_recep.value = str(sum(1 for a in asn if not a.get("bodega") or str(a.get("bodega")) == bodega_act))
            except Exception as ex:
                print(f"[WARN] Indicadores del portal: {ex}")
            cargar_alertas_portal()

        fila_indicadores_portal = ft.ResponsiveRow([
            tarjeta_indicador_portal(lbl_portal_recep, "Recepciones abiertas", "#38BDF8", (1, 0)),
            tarjeta_indicador_portal(lbl_portal_picking, "OV por pickear", "#F59E0B", (3, 2)),
            tarjeta_indicador_portal(lbl_portal_packing, "OV por empacar", "#818CF8", (3, 2)),
            tarjeta_indicador_portal(lbl_portal_fact, "OV por facturar", "#10B981", (3, 3)),
        ], spacing=12, run_spacing=12)

        # ------------------------------------------------------------------
        # REQUIERE ATENCIÓN: alertas de la operación (función wms_alertas_operacion)
        # ------------------------------------------------------------------
        COLOR_SEVERIDAD = {"ALTA": "#EF4444", "MEDIA": "#F59E0B", "BAJA": "#38BDF8"}
        DESTINO_ALERTA = {
            "OLAS": (3, 2), "INVENTARIO": (5, 0), "INVENTARIO_TAREAS": (5, 1), "ALMACENAMIENTO": (2, 0),
            "RUTEO": (7, 0), "MAESTRA": (6, 1), "TRASLADOS": (9, 0), "REABASTECIMIENTO": (2, 1),
        }
        col_alertas_portal = ft.Column(spacing=8, tight=True)
        lbl_resumen_alertas = ft.Text("", size=12, color="#94A3B8")

        def destino_de_alerta(modulo: str):
            dest = DESTINO_ALERTA.get(str(modulo or ""))
            if not dest or dest[0] >= len(vistas_mapa) or not modulo_permitido(dest[0]):
                return None
            return dest

        def abrir_detalle_alerta(alerta: dict):
            items = list(alerta.get("items") or [])
            revisable = bool(alerta.get("revisable"))
            dest = destino_de_alerta(alerta.get("modulo"))
            color = COLOR_SEVERIDAD.get(alerta.get("severidad"), "#94A3B8")
            checks = []
            filas = []
            for it in items[:200]:
                chk = ft.Checkbox(value=False, active_color=color, data=str(it.get("ref") or "")) if revisable else None
                if chk is not None:
                    checks.append(chk)
                filas.append(ft.Container(
                    padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                    border=ft.Border(bottom=ft.BorderSide(0.5, "#334044")),
                    content=ft.Row([
                        *([chk] if chk is not None else []),
                        ft.Text(str(it.get("texto") or it.get("ref") or ""), size=12.5, color="#E2E8F0", expand=True),
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ))
            if len(items) > 200:
                filas.append(ft.Text(f"… y {len(items) - 200} más", size=12, color="#94A3B8"))
            txt_nota = ft.TextField(label="Nota de revisión (qué se hizo)", dense=True, multiline=True,
                                    bgcolor="#1D2426", border_color="#334044", color="#F1F5F9",
                                    text_style=ft.TextStyle(size=12), visible=revisable)

            def cerrar(ev=None):
                try:
                    page.pop_dialog()
                except Exception:
                    dlg.open = False
                page.update()

            def ir_modulo(ev=None):
                cerrar()
                activar_modulo_principal(*dest)

            def marcar_todos(ev=None):
                nuevo = not all(c.value for c in checks)
                for c in checks:
                    c.value = nuevo
                page.update()

            def marcar_revisadas(ev=None):
                refs = [c.data for c in checks if c.value]
                if not refs:
                    notificar_global(page, "Marque los registros que revisó.", "#D97706")
                    return
                if not (txt_nota.value or "").strip():
                    notificar_global(page, "Escriba qué se hizo (nota de revisión).", "#D97706")
                    return
                try:
                    supabase.rpc("wms_marcar_alerta_revisada", {
                        "p_codigo": alerta.get("codigo"), "p_referencias": refs,
                        "p_usuario": str(getattr(page, "usuario_actual", None) or "PC"),
                        "p_nota": txt_nota.value.strip(),
                        "p_bodega": str(getattr(page, "bodega_actual", "") or ""),
                    }).execute()
                except Exception as ex:
                    notificar_global(page, f"No se pudo marcar: {getattr(ex, 'message', None) or ex}", "#B91C1C")
                    return
                cerrar()
                notificar_global(page, f"{len(refs)} registro(s) marcados como revisados.", "#047857")
                cargar_alertas_portal()
                page.update()

            acciones = [ft.TextButton("Cerrar", on_click=cerrar)]
            if revisable:
                acciones.insert(0, ft.OutlinedButton("Marcar / desmarcar todos", on_click=marcar_todos))
                acciones.append(ft.Button(content=ft.Text("Marcar revisadas"), bgcolor="#047857", color=ft.Colors.WHITE,
                                          on_click=marcar_revisadas))
            if dest:
                acciones.append(ft.Button(content=ft.Text("Ir al módulo"), bgcolor="#0284C7", color=ft.Colors.WHITE,
                                          icon=ft.Icons.ARROW_FORWARD_ROUNDED, on_click=ir_modulo))
            dlg = ft.AlertDialog(
                bgcolor="#232B2D",
                title=ft.Column([
                    ft.Row([ft.Container(width=10, height=10, border_radius=5, bgcolor=color),
                            ft.Text(str(alerta.get("titulo") or ""), size=18, weight=ft.FontWeight.W_700, color="#F1F5F9")],
                           spacing=10),
                    ft.Text(f"{alerta.get('cantidad')} registro(s) · {alerta.get('descripcion') or ''}", size=12, color="#94A3B8"),
                ], spacing=4, tight=True),
                content=ft.Container(width=760, height=460, content=ft.Column([
                    ft.Column(filas, spacing=0, scroll=ft.ScrollMode.AUTO, expand=True),
                    txt_nota,
                ], spacing=10, expand=True)),
                actions=acciones,
            )
            page.show_dialog(dlg)

        def fila_alerta(alerta: dict):
            color = COLOR_SEVERIDAD.get(alerta.get("severidad"), "#94A3B8")
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=14, vertical=10), border_radius=10, bgcolor="#232B2D",
                border=ft.Border(left=ft.BorderSide(3, color), top=ft.BorderSide(1, "#334044"),
                                 right=ft.BorderSide(1, "#334044"), bottom=ft.BorderSide(1, "#334044")),
                ink=True, on_click=lambda e, a=alerta: abrir_detalle_alerta(a),
                content=ft.Row([
                    ft.Container(
                        width=46, height=32, border_radius=8, alignment=ft.Alignment.CENTER,
                        bgcolor=ft.Colors.with_opacity(0.16, color),
                        content=ft.Text(str(alerta.get("cantidad") or 0), size=14, weight=ft.FontWeight.W_700, color=color),
                    ),
                    ft.Column([
                        ft.Text(str(alerta.get("titulo") or ""), size=13.5, weight=ft.FontWeight.W_600, color="#F1F5F9"),
                        ft.Text(str(alerta.get("descripcion") or ""), size=11.5, color="#94A3B8", max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=1, tight=True, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color="#64748B"),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )

        def cargar_alertas_portal():
            bodega_act = str(getattr(page, "bodega_actual", "Bodega Santiago") or "Bodega Santiago")
            try:
                alertas = supabase.rpc("wms_alertas_operacion", {"p_bodega": bodega_act}).execute().data or []
            except Exception as ex:
                print(f"[WARN] Alertas del portal: {ex}")
                col_alertas_portal.controls = [ft.Text("No se pudieron leer las alertas (¿falta ejecutar 14_alertas_operacion.sql?).",
                                                       size=12, color="#94A3B8")]
                lbl_resumen_alertas.value = ""
                return
            orden = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}
            alertas.sort(key=lambda a: (orden.get(a.get("severidad"), 3), -int(a.get("cantidad") or 0)))
            if not alertas:
                col_alertas_portal.controls = [ft.Container(
                    padding=14, border_radius=10, bgcolor="#1E2B26", border=ft.Border.all(1, "#14532D"),
                    content=ft.Row([ft.Icon(ft.Icons.VERIFIED_ROUNDED, color="#10B981"),
                                    ft.Text("Todo en orden: no hay alertas en esta bodega.", size=13, color="#D1FAE5")], spacing=10),
                )]
                lbl_resumen_alertas.value = ""
                return
            altas = sum(1 for a in alertas if a.get("severidad") == "ALTA")
            lbl_resumen_alertas.value = f"{len(alertas)} tema(s)" + (f" · {altas} prioritario(s)" if altas else "")
            col_alertas_portal.controls = [
                ft.ResponsiveRow([ft.Container(col={"xs": 12, "lg": 6}, content=fila_alerta(a)) for a in alertas],
                                 spacing=10, run_spacing=10)
            ]

        bloque_alertas_portal = ft.Column([
            ft.Row([ft.Text("Requiere atención", size=15, weight=ft.FontWeight.W_600, color="#CBD5E1"), lbl_resumen_alertas],
                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.END),
            col_alertas_portal,
        ], spacing=10, tight=True)

        vista_portal_home = ft.Row(
            [
                panel_perfil,
                ft.Container(
                    expand=True,
                    padding=ft.Padding.only(left=40, top=32, right=40, bottom=24),
                    alignment=ft.Alignment.TOP_LEFT,
                    content=ft.Column(
                        [
                            ft.Column([
                                ft.Text(f"{saludo}, {nombre_saludo}", size=24, weight=ft.FontWeight.W_700, color="#F1F5F9"),
                                ft.Text(f"{fecha_larga}  ·  {getattr(page, 'bodega_actual', 'Bodega Santiago')}", size=13, color="#94A3B8"),
                            ], spacing=2),
                            fila_indicadores_portal,
                            bloque_alertas_portal,
                            ft.Text("Módulos", size=15, weight=ft.FontWeight.W_600, color="#CBD5E1"),
                            ft.Row(botones_grid, wrap=True, spacing=14, run_spacing=14, alignment=ft.MainAxisAlignment.START),
                        ],
                        spacing=20,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                )
            ], spacing=0, expand=True
        )

        cuerpo_principal = ft.Container(content=vista_portal_home, expand=True)
        btn_home = ft.IconButton(icon=ft.Icons.HOME_OUTLINED, icon_color=ft.Colors.WHITE, tooltip="Volver al Portal de Inicio", on_click=volver_al_home, visible=False)

        menu_apps_rapido = ft.PopupMenuButton(
            icon=ft.Icons.APPS_ROUNDED,
            icon_color=ft.Colors.WHITE,
            tooltip="Acceso rápido a los módulos",
            items=[
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.HOME_OUTLINED, size=18), ft.Text("Inicio")], spacing=10),
                    on_click=volver_al_home,
                ),
            ] + [
                ft.PopupMenuItem(
                    content=ft.Row([
                        ft.Text(f"{idx + 1}. {texto_m.replace(chr(10), ' ')}",
                                color=None if modulo_permitido(idx) else "#94A3B8"),
                        *([] if modulo_permitido(idx) else [ft.Icon(ft.Icons.LOCK_ROUNDED, size=14, color="#94A3B8")]),
                    ], spacing=8),
                    on_click=(lambda e, i=idx: activar_modulo_principal(i)) if modulo_permitido(idx) else avisar_sin_permiso,
                )
                for idx, (texto_m, _, _, _, _, _) in enumerate(vistas_mapa)
            ],
        )

        def cerrar_sesion_actual(e=None):
            nonlocal sesion_activa
            sesion_activa = False
            tarjetas_adaptables.clear()
            kpis_adaptables.clear()
            tablas_scroll_sesion.clear()
            mostrar_pantalla_login()

        puede_cambiar_bodega_pc = bool(getattr(page, "tiene_acceso_multibodega", False))

        def cambiar_bodega_activa_pc(e=None):
            nonlocal sesion_activa
            if not puede_cambiar_bodega_pc:
                dd_bodega_header.value = getattr(page, "bodega_actual", "Bodega Santiago")
                notificar_global(
                    page,
                    f"Acceso restringido: solo puedes operar en {page.bodega_actual}.",
                    "#B91C1C",
                )
                page.update()
                return
            page.bodega_actual = dd_bodega_header.value or "Bodega Santiago"
            fijar_contexto_errores_pc(bodega=page.bodega_actual)
            nueva_es_ccp = "CONCEPCION" in str(page.bodega_actual).upper().replace("Ó", "O")
            if nueva_es_ccp != es_bodega_concepcion:
                # El módulo "Recepción Traslados (Concepción)" se construye al iniciar la torre:
                # al cruzar entre Santiago y Concepción se reconstruye para mostrarlo/ocultarlo.
                sesion_activa = False
                tarjetas_adaptables.clear()
                kpis_adaptables.clear()
                tablas_scroll_sesion.clear()
                iniciar_torre_de_control()
                notificar_global(page, f"Bodega activa cambiada a: {page.bodega_actual}", "#047857")
                return
            notificar_global(page, f"Bodega activa cambiada a: {page.bodega_actual}", "#047857")
            if indice_modulo_activo != -1:
                accion_recarga = vistas_mapa[indice_modulo_activo][3]
                if accion_recarga:
                    accion_recarga()
            else:
                cargar_datos_vivos_panel_izquierdo()
            page.update()

        dd_bodega_header = ft.Dropdown(
            width=195,
            dense=True,
            value=getattr(page, "bodega_actual", "Bodega Santiago"),
            disabled=not puede_cambiar_bodega_pc,
            bgcolor="#1D2426",
            border_color="#334044",
            text_style=ft.TextStyle(size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            options=[
                ft.DropdownOption(key="Bodega Santiago", text="Bodega Santiago"),
                ft.DropdownOption(key="Bodega Concepcion", text="Bodega Concepción"),
            ],
            on_select=cambiar_bodega_activa_pc,
        )

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
                ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.BADGE_OUTLINED, size=18), ft.Text(f"{usuario_logueado} · {rol_logueado}")], spacing=10)),
                ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.CLOUD_DONE_OUTLINED, size=18), ft.Text("Base de datos conectada")], spacing=10)),
                ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.LINK_ROUNDED, size=18), ft.Text(f"NetSuite: {'conectado' if NETSUITE_CONECTADO else 'sin conexión directa'}")], spacing=10)),
                ft.PopupMenuItem(),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.LOGOUT_ROUNDED, size=18, color="#F87171"), ft.Text("Cerrar sesión", color="#F87171")], spacing=10),
                    on_click=cerrar_sesion_actual,
                ),
            ],
        )

        encabezado = ft.Container(
            bgcolor=COLOR_HEADER,
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            content=ft.Row(
                [
                    ft.Row(
                        [
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
                                content=ft.Row(
                                    [
                                        ft.Text("LUDIPEK", color=ft.Colors.WHITE, size=18, weight=ft.FontWeight.W_900),
                                        ft.Container(width=10),
                                        ft.Text("WMS Ludipek", color="#94A3B8", size=13),
                                    ],
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            dd_bodega_header,
                            btn_home,
                            menu_apps_rapido,
                            menu_usuario_header,
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        )

        def adaptar_resolucion_automatica(e=None):
            perfil = obtener_perfil_responsive(page)
            ancho_menu = perfil["menu_width"]
            panel_submenus.width = ancho_menu
            if indice_modulo_activo >= 0:
                panel_submenus.content = generar_menu_lateral(
                    indice_modulo_activo,
                    indice_submodulo_activo,
                    perfil["compacto"],
                )
            modulos_responsive = [dash, recep, puta, pick, mon_cola, inv, mae, imp, ruteo]
            if recep_ccp is not None:
                modulos_responsive.append(recep_ccp)
            for mod_obj in modulos_responsive:
                aplicar_responsive_a_vista(mod_obj.vista, perfil)
            for cont_tabla, h_base in tablas_scroll_sesion:
                cont_tabla.height = max(140, int(h_base * perfil["table_factor"]))
            for tarj in tarjetas_adaptables:
                try:
                    tarj.padding = perfil["card_padding"]
                except Exception:
                    pass
            for card_k, box_ico, txt_val in kpis_adaptables:
                card_k.padding = 7 if perfil["modo"] in ("compacto", "notebook") else 11
                box_ico.padding = 6 if perfil["modo"] in ("compacto", "notebook") else 9
                txt_val.size = 15 if perfil["modo"] in ("compacto", "notebook") else 18
            page.update()

        cargar_datos_vivos_panel_izquierdo()
        cargar_indicadores_portal()
        page.on_resize = adaptar_resolucion_automatica
        page.controls.clear()
        
        page.bgcolor = COLOR_BG_PORTAL
        page.add(ft.Column([encabezado, cuerpo_principal], spacing=0, expand=True))
        adaptar_resolucion_automatica()


if __name__ == "__main__":
    try:
        os.makedirs(os.path.join("assets", "uploads"), exist_ok=True)
        os.makedirs(os.path.join("assets", "descargas"), exist_ok=True)
        if not os.environ.get("FLET_SECRET_KEY"):
            os.environ["FLET_SECRET_KEY"] = os.environ.get("WMS_PASSWORD_SALT", "ludipek_secret_upload_key_2026")

        puerto_cloud = int(os.environ.get("PORT", 8557))
        print(f"[BOOT] Iniciando servidor LUDIPEK WMS en 0.0.0.0:{puerto_cloud}...", flush=True)

        ft.run(
            main,
            view=ft.AppView.WEB_BROWSER,
            port=puerto_cloud,
            host="0.0.0.0",
            assets_dir="assets",
            upload_dir=os.path.join("assets", "uploads"),
        )
    except Exception as ex_boot:
        print(f"[FATAL] Error al iniciar main.py: {ex_boot}", flush=True)
        traceback.print_exc()
        raise