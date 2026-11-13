import os
import math
import time
import shutil
import threading
import traceback
import flet as ft
from dependencias import *
from modulos import m0_dashboard, m1_recepcion, m2_putaway, m3_picking, m4_inventario, m5_maestra, m6_impresion

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
    """Módulo principal independiente para supervisar Operadores RF/PC activos y la Cola de Picking en vivo."""

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
            width=260,
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
            column_spacing=16,
            horizontal_margin=10,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("OPERADOR / USUARIO", weight=ft.FontWeight.BOLD, size=10.5, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("ROL", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("BODEGA", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("ESTADO EN PISO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ÚLTIMA ACCIÓN / ORDEN", weight=ft.FontWeight.BOLD, size=10, color="#FBBF24")),
                ft.DataColumn(ft.Text("MOVIMIENTOS", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("UNID. PROCESADAS", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
            ],
            rows=[],
        )

        tabla_cola_picking = ft.DataTable(
            heading_row_color="#181E20",
            heading_row_height=34,
            data_row_min_height=36,
            data_row_max_height=42,
            column_spacing=16,
            horizontal_margin=10,
            data_text_style=ft.TextStyle(color=TEXT_WHITE),
            columns=[
                ft.DataColumn(ft.Text("PRIORIDAD", weight=ft.FontWeight.BOLD, size=10, color="#A78BFA")),
                ft.DataColumn(ft.Text("OV / OT EN COLA", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                ft.DataColumn(ft.Text("CANAL", weight=ft.FontWeight.BOLD, size=10, color="#FBBF24")),
                ft.DataColumn(ft.Text("FECHA OV", weight=ft.FontWeight.BOLD, size=10, color="#34D399")),
                ft.DataColumn(ft.Text("CLIENTE / DESTINO", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("ETAPA EN COLA", weight=ft.FontWeight.BOLD, size=10, color=TEXT_WHITE)),
                ft.DataColumn(ft.Text("OPERADOR RF", weight=ft.FontWeight.BOLD, size=10, color=ACCENT_CYAN)),
            ],
            rows=[],
        )

        cont_tabla_usuarios = envolver_tabla_scroll(tabla_usuarios_rf, 250)
        cont_tabla_cola = envolver_tabla_scroll(tabla_cola_picking, 310)

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

                mapa_op_por_ov = {}
                try:
                    res_pl = supabase.table("wms_packing_lists_fa").select("*").order("id", desc=True).limit(200).execute()
                    for pl in (res_pl.data or []):
                        if not coincide_bodega(pl, bodega_act):
                            continue
                        ov_k = str(pl.get("numero_ov") or "").split("(")[0].strip().upper().removesuffix("-FA").strip()
                        op_k = str(pl.get("usuario_picking") or "").strip().upper()
                        if ov_k and op_k and ov_k not in mapa_op_por_ov:
                            mapa_op_por_ov[ov_k] = op_k
                        if op_k:
                            if op_k not in mapa_actividad_usr:
                                mapa_actividad_usr[op_k] = {
                                    "ultimo_mov": f"PACKING OV {ov_k}",
                                    "conteo": 0,
                                    "unidades": 0,
                                }
                            mapa_actividad_usr[op_k]["conteo"] += 1
                except Exception:
                    pass

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

                    badge_est = (
                        crear_badge_estado("ACTIVO EN PISO", "#065F46", "#D1FAE5")
                        if cnt_m > 0
                        else crear_badge_estado("HABILITADO", "#1E3A8A", "#DBEAFE")
                    )

                    filas_u.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(f"{nom_u} ({cod_u})", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(rol_u, size=10.5, color=TEXT_WHITE)),
                                ft.DataCell(ft.Text(bod_u, size=10.5, color="#34D399")),
                                ft.DataCell(badge_est),
                                ft.DataCell(ft.Text(ult_txt[:38], size=10.5, color="#FBBF24")),
                                ft.DataCell(ft.Text(f"{cnt_m} movs", weight=ft.FontWeight.BOLD, size=11, color=ACCENT_CYAN)),
                                ft.DataCell(ft.Text(f"{unid_m} UN", weight=ft.FontWeight.BOLD, size=11, color="#34D399")),
                            ]
                        )
                    )
                tabla_usuarios_rf.rows = filas_u

                res_ov = supabase.table("netsuite_ordenes_venta").select("*").order("id", desc=True).limit(400).execute()
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
                    if est_ov == "PENDIENTE_PACKING":
                        cnt_pend_pack += 1
                    else:
                        cnt_pend_pick += 1

                    cli_str = str(r.get("cliente_nombre") or r.get("cliente") or "CLIENTE").strip()
                    canal_str = str(r.get("canal_venta") or "").upper()
                    es_fa = ov_raw.endswith("-FA") or "FARM" in canal_str or ov_raw.startswith("OT-")
                    fecha_s = str(r.get("fecha_emision_ns") or r.get("created_at") or "")[:10]
                    op_asig = str(r.get("operador_asignado") or mapa_op_por_ov.get(ov_base) or "EN COLA GENERAL").upper()

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

                    filas_cola.append(
                        ft.DataRow(
                            color="#2A2419" if es_fa else None,
                            cells=[
                                ft.DataCell(ft.Text("ALTA (-FA)" if es_fa else "NORMAL", weight=ft.FontWeight.BOLD, size=10.5, color="#FBBF24" if es_fa else "#A78BFA")),
                                ft.DataCell(ft.Text(ov_raw, weight=ft.FontWeight.W_900, size=11.5, color="#FBBF24" if es_fa else ACCENT_CYAN)),
                                ft.DataCell(badge_canal),
                                ft.DataCell(ft.Text(fecha_s, size=11, color="#34D399")),
                                ft.DataCell(ft.Text(cli_str[:32], size=11, color=TEXT_WHITE)),
                                ft.DataCell(badge_etapa),
                                ft.DataCell(ft.Text(op_asig, weight=ft.FontWeight.BOLD, size=10.5, color=ACCENT_CYAN)),
                            ],
                        )
                    )

                tabla_cola_picking.rows = filas_cola
                lbl_kpi_usr_activos.value = str(len(usuarios_lista))
                lbl_kpi_cola_pend.value = str(cnt_pend_pick)
                lbl_kpi_en_pack.value = str(cnt_pend_pack)
                lbl_kpi_movs_hoy.value = str(movs_totales)
                self.page.update()
            except Exception as ex:
                print(f"[WARN] Error refrescando Monitor Usuarios y Cola: {ex}")

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
                                "MONITOR DE USUARIOS RF & COLA DE PICKING EN VIVO",
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
                                "ACTUALIZAR EN VIVO",
                                _ico("SYNC_ROUNDED", "REFRESH_ROUNDED"),
                                refrescar_monitor_usuarios_y_cola,
                                ACCENT_BLUE,
                                height_val=34,
                            ),
                        ],
                        spacing=8,
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
                            ft.Text("1. MONITOR DE OPERADORES RF / PC Y ACTIVIDAD EN PISO", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
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
                            ft.Text("2. COLA ACTIVA DE PICKING Y PACKING (PRIORIDAD NORMAL VS FARMACIA -FA)", size=13, weight=ft.FontWeight.BOLD, color=TEXT_WHITE),
                        ],
                        spacing=8,
                    ),
                    ft.Divider(color=BORDER_COLOR, height=2),
                    cont_tabla_cola,
                ],
                spacing=8,
            ),
        )

        self.sub_completo = ft.Column([fila_kpis, tarjeta_usuarios, tarjeta_cola], spacing=10)
        self.sub_solo_cola = ft.Column([fila_kpis, tarjeta_cola], spacing=10)
        self.sub_solo_usuarios = ft.Column([fila_kpis, tarjeta_usuarios], spacing=10)
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
            res = supabase.table("wms_usuarios").select("*").ilike("usuario", user_val).limit(1).execute()
            fila_u = res.data[0] if res.data else None

            if fila_u and fila_u.get("activo") and verificar_password_seguro(pass_val, fila_u.get("password", "")):
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

                mod_pc_str = str(fila_u.get("modulos_pc") or fila_u.get("permisos_pc") or "").strip()
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
                    ("1. Vista Integral (BI + POs)", _ico("VIEW_IN_AR_OUTLINED", "DASHBOARD_OUTLINED")),
                    ("2. Productividad & Dock-to-Stock", _ico("PRECISION_MANUFACTURING_OUTLINED", "BOLT_ROUNDED")),
                    ("3. Ocupación, Quiebres & Dead Stock", _ico("CATEGORY_OUTLINED", "PIE_CHART_OUTLINE_ROUNDED")),
                ],
            ),
            (
                "Recepción\n(Ingresos PO)",
                _ico("ALL_INBOX_OUTLINED", "INVENTORY_2_OUTLINED"),
                recep.vista,
                recep.cargar_lista_asns,
                recep.sel_sub_inb,
                [
                    ("1. Recepción Activa (PO)", _ico("INVENTORY_2_OUTLINED", "FACT_CHECK_OUTLINED")),
                    ("2. Consultas de Recepción", _ico("QR_CODE_SCANNER_OUTLINED", "QR_CODE_SCANNER", "MANAGE_SEARCH_ROUNDED")),
                    ("3. Control Calidad (QA por PO)", _ico("CENTER_FOCUS_STRONG_OUTLINED", "VERIFIED_USER_OUTLINED")),
                    ("4. Modificación de PO y LPNs", _ico("CROP_FREE_OUTLINED", "CROP_FREE", "EDIT_NOTE_ROUNDED")),
                ],
            ),
            (
                "Almacenamiento\n(Mov. LPN)",
                _ico("VIEW_IN_AR_OUTLINED", "WIDGETS_OUTLINED"),
                puta.vista,
                puta.cargar_inventario_ubicaciones,
                puta.sel_sub_put,
                [
                    ("1. Putaway & Mapa de Stock", _ico("ALL_INBOX_OUTLINED", "DOMAIN_OUTLINED")),
                    ("2. Reabastecimiento (Reserva -> N1)", _ico("INVENTORY_2_OUTLINED", "ARROW_DOWNWARD_ROUNDED")),
                    ("3. Vista Combinada", _ico("CATEGORY_OUTLINED", "VIEW_AGENDA_OUTLINED")),
                    ("4. Gemelo Digital 3D", _ico("TOKEN_OUTLINED", "VIEW_IN_AR_ROUNDED")),
                ],
            ),
            (
                "Olas\n(Packing)",
                _ico("INVENTORY_2_OUTLINED", "VIEW_IN_AR_OUTLINED"),
                pick.vista,
                pick.cargar_monitor_packing_dual,
                pick.sel_sub_olas,
                [
                    ("1. Monitor Completo (Olas + Packing)", _ico("VIEW_IN_AR_OUTLINED", "VIEW_QUILT_OUTLINED")),
                    ("2. Extracción Olas NetSuite", _ico("ALL_INBOX_OUTLINED", "CLOUD_DOWNLOAD_OUTLINED")),
                    ("3. Listado Órdenes de Venta", _ico("INVENTORY_2_OUTLINED", "INVENTORY_OUTLINED")),
                    ("4. Facturación (Subida NetSuite)", _ico("CENTER_FOCUS_STRONG_OUTLINED", "RECEIPT_LONG_ROUNDED")),
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
                    ("1. Pasillos y Cruce ERP", _ico("VIEW_IN_AR_OUTLINED", "RULE_ROUNDED")),
                    ("2. SKU Dirigido & Ubic. Vacías", _ico("CENTER_FOCUS_WEAK_OUTLINED", "TRACK_CHANGES_ROUNDED")),
                    ("3. Trazabilidad LPN / Rack", _ico("QR_CODE_SCANNER_OUTLINED", "QR_CODE_SCANNER", "HISTORY_ROUNDED")),
                    ("4. Alertas y Desvíos (RF)", _ico("CROP_FREE_OUTLINED", "CROP_FREE", "WARNING_AMBER_ROUNDED")),
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
            nonlocal indice_modulo_activo
            codigos_mod = [
                "PC_DASHBOARD",
                "PC_RECEPCION",
                "PC_ALMACENAMIENTO",
                "PC_OLAS",
                "PC_OLAS",
                "PC_INVENTARIO",
                "PC_ADMIN_MAESTRA",
                "PC_IMPRESION",
            ]
            rol_usr = str(getattr(page, "rol_actual", "")).upper()
            permisos_str = str(getattr(page, "modulos_pc_usuario", "")).upper()
            if "ADMIN" not in rol_usr and permisos_str and codigos_mod[idx_sel] not in permisos_str:
                notificar_global(page, "Acceso restringido: tu perfil no tiene permisos para este módulo.", "#B91C1C")
                return

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
                            ft.Text(texto_mod, size=13.5, weight=ft.FontWeight.W_500, color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER)
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12
                    )
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
                    padding=ft.Padding.only(left=70, top=50, right=50, bottom=20),
                    alignment=ft.Alignment.TOP_LEFT,
                    content=ft.Column(
                        [
                            ft.Row(botones_grid, wrap=True, spacing=36, run_spacing=40, alignment=ft.MainAxisAlignment.START),
                            ft.Container(height=45),
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

        menu_apps_rapido = ft.PopupMenuButton(
            icon=ft.Icons.APPS_ROUNDED,
            icon_color=ft.Colors.WHITE,
            tooltip="Acceso rápido a los 8 módulos WMS",
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
            tarjetas_adaptables.clear()
            kpis_adaptables.clear()
            tablas_scroll_sesion.clear()
            mostrar_pantalla_login()

        puede_cambiar_bodega_pc = bool(getattr(page, "tiene_acceso_multibodega", False))

        def cambiar_bodega_activa_pc(e=None):
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
            bgcolor="#232A2B",
            border_color="#38BDF8" if puede_cambiar_bodega_pc else "#475569",
            text_style=ft.TextStyle(size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            options=[
                ft.DropdownOption(key="Bodega Santiago", text="📍 Bodega Santiago"),
                ft.DropdownOption(key="Bodega Concepcion", text="📍 Bodega Concepcion"),
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
            ancho_w = page.width or 1366
            alto_h = page.height or 768
            es_notebook = (ancho_w <= 1500) or (alto_h <= 860)

            pad_vista = 8 if es_notebook else 14
            pad_tarjeta = 10 if es_notebook else 14

            ancho_menu = 200 if es_notebook else 245
            panel_submenus.width = ancho_menu
            if panel_submenus.content and hasattr(panel_submenus.content, "width"):
                panel_submenus.content.width = ancho_menu

            for mod_obj in (dash, recep, puta, pick, mon_cola, inv, mae, imp):
                mod_obj.vista.padding = ft.Padding.only(
                    left=pad_vista, top=pad_vista, right=pad_vista + 6, bottom=pad_vista
                )
                if hasattr(mod_obj.vista, "content") and isinstance(mod_obj.vista.content, ft.Column):
                    mod_obj.vista.content.scroll = ft.ScrollMode.ALWAYS

            factor_alto = 0.72 if alto_h <= 780 else (0.85 if alto_h <= 920 else 1.05)
            for cont_tabla, h_base in tablas_scroll_sesion:
                cont_tabla.height = max(145, int(h_base * factor_alto))

            for tarj in tarjetas_adaptables:
                tarj.padding = pad_tarjeta
            for card_k, box_ico, txt_val in kpis_adaptables:
                card_k.padding = 8 if es_notebook else 12
                box_ico.padding = 6 if es_notebook else 10
                txt_val.size = 15 if es_notebook else 20

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