"""Centro del desarrollador (m9) y "Reportar un problema".

· Módulo Desarrollador (permiso PC_DESARROLLADOR, ni siquiera los ADMIN lo ven sin él):
    0 Resumen  · errores por día (celular / PC), pendientes, tickets, versiones en uso
    1 Errores  · agrupados por firma (mismo error aunque cambie un número), con estado
    2 Tickets  · reportes de los usuarios: estado, prioridad, comentarios y respuesta
· abrir_reportar_problema(page, modulo): diálogo para que cualquier usuario del PC reporte.
· abrir_mis_reportes(page): el usuario ve el estado y la respuesta de sus reportes.
Requiere 34_centro_desarrollador.sql.
"""
from datetime import datetime, timedelta, timezone

import flet as ft

from dependencias import (supabase, UI, ui_boton, ui_kpi, ui_tabla, notificar_global, formatear_fecha_hora_chile,
                          obtener_bodega_activa, CONTEXTO_ERRORES_PC)

INK, INK_2, INK_3 = UI["texto"], UI["texto_2"], UI["texto_3"]
GRILLA, BASE = "#2E393C", "#3B484B"
SERIE_RF = ("rf", "Celular", "#3987e5")      # par categórico validado (CVD) sobre #232B2D
SERIE_PC = ("pc", "PC", "#d95926")
ESTADO = {"bueno": "#0ca30c", "advertencia": "#fab219", "serio": "#ec835a", "critico": "#d03b3b"}

EST_ERROR = {   # estado -> (texto, nivel o color, icono)
    "NUEVO": ("Nuevo", ESTADO["serio"], ft.Icons.FIBER_NEW_OUTLINED),
    "REAPARECIO": ("Reapareció", ESTADO["critico"], ft.Icons.REPLAY_ROUNDED),
    "EN_REVISION": ("En revisión", ESTADO["advertencia"], ft.Icons.MANAGE_SEARCH_ROUNDED),
    "RESUELTO": ("Resuelto", ESTADO["bueno"], ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED),
    "IGNORADO": ("Ignorado", INK_3, ft.Icons.VISIBILITY_OFF_OUTLINED),
}
EST_TICKET = {
    "NUEVO": ("Nuevo", ESTADO["serio"], ft.Icons.FIBER_NEW_OUTLINED),
    "EN_REVISION": ("En revisión", ESTADO["advertencia"], ft.Icons.MANAGE_SEARCH_ROUNDED),
    "EN_DESARROLLO": ("En desarrollo", "#3987e5", ft.Icons.CODE_ROUNDED),
    "RESUELTO": ("Resuelto", ESTADO["bueno"], ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED),
    "DESCARTADO": ("Descartado", INK_3, ft.Icons.DO_NOT_DISTURB_ON_OUTLINED),
}
PRIORIDAD = {
    "BAJA": ("Baja", INK_3, ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED),
    "MEDIA": ("Media", "#3987e5", ft.Icons.REMOVE_ROUNDED),
    "ALTA": ("Alta", ESTADO["serio"], ft.Icons.KEYBOARD_ARROW_UP_ROUNDED),
    "CRITICA": ("Crítica", ESTADO["critico"], ft.Icons.PRIORITY_HIGH_ROUNDED),
}
TIPOS = {"PROBLEMA": "Algo no funciona", "ERROR": "Apareció un error", "MEJORA": "Sugerencia de mejora",
         "CONSULTA": "Consulta / duda"}


# ---------------------------------------------------------------------
# utilidades visuales
# ---------------------------------------------------------------------
def _miles(n) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except Exception:
        return str(n or 0)


def _t(txt, peso=None, color=None, size=12, **kw):
    return ft.Text(str(txt if txt is not None else ""), size=size, weight=peso, color=color or INK, **kw)


def _chip(info: tuple):
    texto, color, icono = info
    return ft.Row([ft.Icon(icono, size=14, color=color), ft.Text(texto, size=11.5, color=INK_2)], spacing=4, tight=True)


def _col(txt, numerica=False):
    return ft.DataColumn(ft.Text(txt, size=11.5, weight=ft.FontWeight.W_600, color=INK_2), numeric=numerica)


def _tarjeta(titulo, subtitulo, contenido, col=None, accion=None):
    return ft.Container(
        col=col, padding=16, bgcolor=UI["card"], border_radius=10, border=ft.Border.all(1, UI["borde"]),
        content=ft.Column([
            ft.Row([
                ft.Column([ft.Text(titulo, size=14, weight=ft.FontWeight.W_600, color=INK),
                           ft.Text(subtitulo, size=11, color=INK_2)], spacing=2, tight=True, expand=True),
                *([accion] if accion else []),
            ], vertical_alignment=ft.CrossAxisAlignment.START),
            contenido,
        ], spacing=14, tight=True),
    )


def _vacio(texto):
    return ft.Container(height=90, alignment=ft.Alignment.CENTER,
                        content=ft.Text(texto, size=12, color=INK_3, text_align=ft.TextAlign.CENTER))


def _campo(label, valor="", ancho=None, multilinea=False, expand=None):
    return ft.TextField(label=label, value=valor, width=ancho, expand=expand, dense=True, text_size=12.5,
                        multiline=multilinea, min_lines=3 if multilinea else None, max_lines=8 if multilinea else None,
                        color=INK, bgcolor=UI["input"], border_color=UI["borde"], focused_border_color=UI["acento"],
                        label_style=ft.TextStyle(size=11, color=INK_2))


def _dropdown(label, opciones: dict, valor, ancho=200):
    return ft.Dropdown(
        label=label, value=valor, width=ancho, dense=True, color=INK, bgcolor=UI["input"], border_color=UI["borde"],
        focused_border_color=UI["acento"], text_style=ft.TextStyle(size=12, color=INK),
        label_style=ft.TextStyle(size=11, color=INK_2), border_radius=6,
        options=[ft.DropdownOption(key=k, text=v, content=ft.Text(v, size=12, color=INK)) for k, v in opciones.items()],
    )


def _filtros(opciones: list, actual: str, al_elegir):
    """Fila de pastillas de filtro. opciones: [(clave, texto)]."""
    return ft.Row([
        ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=6), border_radius=16, ink=True,
            bgcolor=ft.Colors.with_opacity(0.18, UI["acento"]) if k == actual else UI["card_alt"],
            border=ft.Border.all(1, UI["acento"] if k == actual else UI["borde"]),
            on_click=lambda e, x=k: al_elegir(x),
            content=ft.Text(txt, size=11.5, color=INK, weight=ft.FontWeight.W_600 if k == actual else None),
        ) for k, txt in opciones
    ], spacing=6, wrap=True, run_spacing=6)


def _version_tupla(v):
    try:
        return tuple(int(x) for x in str(v or "").strip().split("."))
    except Exception:
        return ()


def _cerrar(page):
    try:
        page.pop_dialog()
    except Exception:
        pass


def _msg_error(ex) -> str:
    msg = str(getattr(ex, "message", None) or ex)
    if any(n in msg for n in ("wms_tickets", "wms_reportar_problema", "wms_mis_tickets", "wms_errores_grupos",
                              "wms_dev_resumen")) and ("not find" in msg or "does not exist" in msg):
        return "falta ejecutar 34_centro_desarrollador.sql en Supabase"
    return msg.replace("WMS: ", "")


def _usuario(page):
    return str(getattr(page, "usuario_actual", "") or CONTEXTO_ERRORES_PC.get("usuario") or "PC")


# ---------------------------------------------------------------------
# Reportar un problema (cualquier usuario del PC)
# ---------------------------------------------------------------------
def abrir_reportar_problema(page: ft.Page, modulo: str = ""):
    dd_tipo = _dropdown("¿Qué quiere reportar?", TIPOS, "PROBLEMA", 300)
    txt_titulo = _campo("En pocas palabras, ¿qué pasó?", ancho=460)
    txt_desc = _campo("Detalle: qué estaba haciendo, qué esperaba y qué pasó (OC, LPN, OV…)", ancho=460, multilinea=True)
    chk_bloquea = ft.Checkbox(label="Me impide seguir trabajando", value=False,
                              label_style=ft.TextStyle(size=12, color=INK))
    lbl_err = ft.Text("", size=12, color="#F87171")

    def enviar(e=None):
        titulo = (txt_titulo.value or "").strip()
        if len(titulo) < 4:
            lbl_err.value = "Escriba en pocas palabras qué pasó."
            page.update()
            return
        try:
            r = supabase.rpc("wms_reportar_problema", {
                "p_origen": "PC", "p_modulo": modulo or None, "p_tipo": dd_tipo.value or "PROBLEMA",
                "p_titulo": titulo, "p_descripcion": (txt_desc.value or "").strip() or None,
                "p_usuario": _usuario(page), "p_bodega": obtener_bodega_activa(page),
                "p_version": CONTEXTO_ERRORES_PC.get("version") or "PC", "p_dispositivo": "PC",
                "p_prioridad": "ALTA" if chk_bloquea.value else "MEDIA",
            }).execute().data or {}
        except Exception as ex:
            lbl_err.value = f"No se envió: {_msg_error(ex)}"
            page.update()
            return
        _cerrar(page)
        notificar_global(page, f"Reporte #{r.get('id', '')} enviado. Puede ver su estado en su perfil › Mis reportes.", "#047857")

    page.show_dialog(ft.AlertDialog(
        modal=True,
        title=ft.Row([ft.Icon(ft.Icons.BUG_REPORT_OUTLINED, color=UI["acento"]),
                      ft.Text("Reportar un problema", weight=ft.FontWeight.BOLD)], spacing=8),
        content=ft.Container(width=480, content=ft.Column([
            ft.Text(f"Pantalla: {modulo}" if modulo else "Pantalla: inicio", size=11.5, color=INK_2),
            dd_tipo, txt_titulo, txt_desc, chk_bloquea, lbl_err,
            ft.Text("Se envía con su usuario, bodega y pantalla. Los errores técnicos ya se registran solos; "
                    "aquí cuente lo que vio.", size=11, color=INK_3),
        ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO)),
        actions=[ui_boton("Mis reportes", ft.Icons.LIST_ALT_ROUNDED, lambda e: (_cerrar(page), abrir_mis_reportes(page)), "texto"),
                 ui_boton("Cancelar", None, lambda e: _cerrar(page), "texto"),
                 ui_boton("Enviar", ft.Icons.SEND_ROUNDED, enviar, "primario")],
        actions_alignment=ft.MainAxisAlignment.END,
    ))


def abrir_mis_reportes(page: ft.Page):
    try:
        datos = supabase.rpc("wms_mis_tickets", {"p_usuario": _usuario(page)}).execute().data or []
    except Exception as ex:
        notificar_global(page, f"No se pudieron leer sus reportes: {_msg_error(ex)}", "#B45309")
        return
    items = []
    for t in datos:
        coms = [ft.Text(f"{c.get('fecha')} · {c.get('usuario') or ''}: {c.get('texto')}", size=11.5, color=INK_2)
                for c in (t.get("comentarios") or [])]
        items.append(ft.Container(
            padding=12, border_radius=8, bgcolor=UI["card_alt"], border=ft.Border.all(1, UI["borde"]),
            content=ft.Column([
                ft.Row([ft.Text(f"#{t.get('id')} · {t.get('titulo')}", size=12.5, weight=ft.FontWeight.W_600,
                                color=INK, expand=True),
                        _chip(EST_TICKET.get(t.get("estado"), (t.get("estado"), INK_3, ft.Icons.CIRCLE_OUTLINED)))]),
                ft.Text(f"{TIPOS.get(t.get('tipo'), t.get('tipo'))} · {t.get('modulo') or '-'} · {t.get('creado')}",
                        size=11, color=INK_3),
                *([ft.Text(f"Respuesta: {t.get('respuesta')}", size=12, color=INK)] if t.get("respuesta") else []),
                *coms,
            ], spacing=4, tight=True),
        ))
    page.show_dialog(ft.AlertDialog(
        title=ft.Text("Mis reportes", weight=ft.FontWeight.BOLD),
        content=ft.Container(width=520, height=420, content=ft.Column(
            items or [_vacio("Aún no ha enviado reportes.")], spacing=8, scroll=ft.ScrollMode.AUTO)),
        actions=[ui_boton("Nuevo reporte", ft.Icons.BUG_REPORT_OUTLINED,
                          lambda e: (_cerrar(page), abrir_reportar_problema(page, "")), "secundario"),
                 ui_boton("Cerrar", None, lambda e: _cerrar(page), "texto")],
        actions_alignment=ft.MainAxisAlignment.END,
    ))


# ---------------------------------------------------------------------
# Gráfico: errores por día (columnas agrupadas Celular / PC)
# ---------------------------------------------------------------------
def _grafico_dias(dias: list, alto=170):
    series = [SERIE_RF, SERIE_PC]
    if not dias or not any(d.get(k, 0) for d in dias for k, _, _ in series):
        return _vacio("Sin errores registrados en el período.")
    maximo = max(max(int(d.get(k, 0) or 0) for k, _, _ in series) for d in dias)
    tope = 5
    while tope < maximo:
        tope = tope * 2 if str(tope)[0] in "15" else int(tope * 2.5)
    eje_y = ft.Column([ft.Text(_miles(tope * f), size=10, color=INK_3, text_align=ft.TextAlign.RIGHT, width=32)
                       for f in (1, 0.75, 0.5, 0.25, 0)],
                      height=alto + 8, alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                      horizontal_alignment=ft.CrossAxisAlignment.END)
    grilla = ft.Column([ft.Container(expand=True, border=ft.Border(top=ft.BorderSide(1, GRILLA))) for _ in range(4)]
                       + [ft.Container(height=0, border=ft.Border(top=ft.BorderSide(1, BASE)))],
                       spacing=0, height=alto, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    grupos = []
    for d in dias:
        barras = []
        for k, _, color in series:
            v = int(d.get(k, 0) or 0)
            barras.append(ft.Container(width=7, height=0 if v <= 0 else max(2, v / tope * alto), bgcolor=color,
                                       border_radius=ft.BorderRadius(top_left=3, top_right=3, bottom_left=0, bottom_right=0)))
        grupos.append(ft.Container(expand=True, height=alto,
                                   tooltip=f"{d.get('dia')}\nCelular: {_miles(d.get('rf'))}\nPC: {_miles(d.get('pc'))}",
                                   content=ft.Row(barras, spacing=2, alignment=ft.MainAxisAlignment.CENTER,
                                                  vertical_alignment=ft.CrossAxisAlignment.END)))
    n = len(dias)
    eje_x = ft.Row([ft.Text(str(d.get("dia", ""))[:2] if (i % 2 == 0 or i == n - 1) else "", size=10, color=INK_2,
                            text_align=ft.TextAlign.CENTER, expand=True) for i, d in enumerate(dias)], spacing=0)
    tot = {k: sum(int(d.get(k, 0) or 0) for d in dias) for k, _, _ in series}
    leyenda = ft.Row([ft.Row([ft.Container(width=10, height=10, border_radius=2, bgcolor=c),
                              ft.Text(f"{nom} · {_miles(tot[k])}", size=11, color=INK_2)], spacing=6, tight=True)
                      for k, nom, c in series], spacing=16)
    return ft.Column([leyenda, ft.Row([eje_y, ft.Column([ft.Stack([grilla, ft.Row(grupos, spacing=0, height=alto)],
                                                                  height=alto), eje_x], spacing=4, expand=True)],
                                      spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)], spacing=12)


def _barra_h(etiqueta, valor, tope, texto, color="#3987e5"):
    largo = 0 if tope <= 0 else int(max(0.0, min(1.0, valor / tope)) * 1000)
    return ft.Row([
        ft.Text(etiqueta, size=12, color=INK_2, width=170, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=etiqueta),
        ft.Container(expand=True, height=12, content=ft.Row([
            *([ft.Container(expand=largo, height=12, bgcolor=color,
                            border_radius=ft.BorderRadius(top_left=0, top_right=4, bottom_left=0, bottom_right=4))] if largo else []),
            *([ft.Container(expand=1000 - largo)] if largo < 1000 else []),
        ], spacing=0)),
        ft.Text(texto, size=12, color=INK, width=48, text_align=ft.TextAlign.RIGHT),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)


# ---------------------------------------------------------------------
# Módulo Desarrollador
# ---------------------------------------------------------------------
class DesarrolladorModulo:
    def __init__(self, page: ft.Page, tarjetas_adaptables: list = None, kpis_adaptables: list = None):
        self.page = page
        self.sub = 0
        self.filtro_err = "PENDIENTES"
        self.filtro_origen = "TODOS"
        self.filtro_tk = "ABIERTOS"
        self.contenedor = ft.Column(spacing=12)
        self.lbl_generado = ft.Text("", size=11, color=INK_3)
        self.txt_buscar = _campo("Buscar en mensaje, módulo o usuario", ancho=300)
        self.txt_buscar.on_submit = lambda e: self._construir()
        cab = ft.Row([
            ft.Icon(ft.Icons.TERMINAL_ROUNDED, color=UI["acento"]),
            ft.Column([ft.Text("Centro del desarrollador", size=16, weight=ft.FontWeight.W_700, color=INK),
                       self.lbl_generado], spacing=0, tight=True, expand=True),
            ui_boton("Actualizar", ft.Icons.REFRESH_ROUNDED, lambda e: self._construir(), "secundario"),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.vista = ft.Container(expand=True, padding=16, content=ft.Column(
            [cab, self.contenedor], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True))

    def refrescar(self, e=None):
        self._construir()

    def sel_sub_dev(self, idx: int):
        self.sub = idx if idx in (0, 1, 2) else 0

    def _update(self):
        try:
            self.page.update()
        except Exception:
            pass

    def _construir(self):
        try:
            if self.sub == 1:
                controles = self._vista_errores()
            elif self.sub == 2:
                controles = self._vista_tickets()
            else:
                controles = self._vista_resumen()
        except Exception as ex:
            controles = [_tarjeta("No se pudo cargar", _msg_error(ex), ft.Container())]
        self.contenedor.controls = controles
        self.lbl_generado.value = "Actualizado " + datetime.now().strftime("%H:%M:%S")
        self._update()

    # ------------------------------------------------------------- 0 Resumen
    def _vista_resumen(self):
        d = supabase.rpc("wms_dev_resumen", {"p_dias": 14}).execute().data or {}
        k = d.get("kpis") or {}
        det = lambda t: ft.Text(t, size=11, color=INK_3)
        col = {"xs": 12, "sm": 6, "md": 4, "xl": 2}
        tiles = ft.ResponsiveRow([
            ui_kpi(ft.Text(_miles(k.get("errores_24h"))), "Errores últimas 24 h", ft.Icons.ERROR_OUTLINE_ROUNDED, ESTADO["serio"],
                   det(f"{_miles(k.get('errores_24h_rf'))} del celular · {_miles(k.get('usuarios_24h'))} usuarios"), col=col),
            ui_kpi(ft.Text(_miles(k.get("grupos_pendientes"))), "Errores por revisar", ft.Icons.MANAGE_SEARCH_ROUNDED,
                   ESTADO["advertencia"], det(f"{_miles(k.get('grupos_nuevos'))} nuevos"), col=col),
            ui_kpi(ft.Text(_miles(k.get("reaparecidos"))), "Reaparecieron", ft.Icons.REPLAY_ROUNDED,
                   ESTADO["critico"] if int(k.get("reaparecidos") or 0) else ESTADO["bueno"],
                   det("marcados resueltos que volvieron"), col=col),
            ui_kpi(ft.Text(_miles(k.get("tickets_abiertos"))), "Tickets abiertos", ft.Icons.CONFIRMATION_NUMBER_OUTLINED,
                   "#3987e5", det(f"{_miles(k.get('tickets_nuevos'))} sin revisar"), col=col),
            ui_kpi(ft.Text(_miles(k.get("tickets_urgentes"))), "Tickets urgentes", ft.Icons.PRIORITY_HIGH_ROUNDED,
                   ESTADO["critico"] if int(k.get("tickets_urgentes") or 0) else ESTADO["bueno"],
                   det("prioridad alta o crítica"), col=col),
        ], spacing=12, run_spacing=12)

        mods = d.get("por_modulo") or []
        tope = max([int(m.get("n") or 0) for m in mods] or [0])
        card_mod = _tarjeta("Dónde ocurren", "Errores por módulo, últimos 14 días", ft.Column(
            [_barra_h(f"{m.get('modulo')} · {'Celular' if m.get('origen') == 'RF' else 'PC'}", int(m.get("n") or 0), tope,
                      _miles(m.get("n")), SERIE_RF[2] if m.get("origen") == "RF" else SERIE_PC[2]) for m in mods]
            or [_vacio("Sin errores en el período.")], spacing=10), col={"xs": 12, "lg": 5})

        card_dias = _tarjeta("Errores por día", "Celular y PC, últimos 14 días (pase el mouse para ver el detalle)",
                             _grafico_dias(d.get("por_dia") or []), col={"xs": 12, "lg": 7})

        # Versiones en uso
        vmin = str(d.get("version_minima") or "")
        sesiones = d.get("sesiones") or []
        versiones = [s.get("version") for s in sesiones if s.get("version")]
        ultima = max(versiones, key=_version_tupla) if versiones else ""
        filas = []
        for s in sesiones[:40]:
            v = s.get("version") or ""
            if not v:
                estado = ("Sin dato (app anterior)", ESTADO["advertencia"], ft.Icons.HELP_OUTLINE_ROUNDED)
            elif ultima and _version_tupla(v) < _version_tupla(ultima):
                estado = ("Desactualizada", ESTADO["serio"], ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED)
            else:
                estado = ("Al día", ESTADO["bueno"], ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED)
            filas.append(ft.DataRow(cells=[
                ft.DataCell(_t(s.get("usuario"), ft.FontWeight.W_600)), ft.DataCell(_t(s.get("nombre") or "", color=INK_2)),
                ft.DataCell(_t(s.get("bodega") or "", color=INK_2)), ft.DataCell(_t(v or "-")),
                ft.DataCell(_chip(estado)), ft.DataCell(_t(s.get("ultimo_uso"), color=INK_2)),
                ft.DataCell(_t("Abierta" if s.get("abierta") else "Cerrada", color=INK_2)),
            ]))
        tabla_ses = ft.DataTable(columns=[_col("Usuario"), _col("Nombre"), _col("Bodega"), _col("Versión app"),
                                          _col("Estado"), _col("Último uso"), _col("Sesión")], rows=filas)
        vers_err = d.get("versiones_errores") or []
        card_ver = _tarjeta(
            "Versiones en uso (celulares)",
            f"Sesiones usadas en las últimas 24 h · versión mínima exigida: {vmin or '-'} · más nueva vista: {ultima or '-'}",
            ft.Column([
                ui_tabla(tabla_ses, 260) if filas else _vacio("Sin sesiones en las últimas 24 h."),
                ft.Text("La versión aparece en sesiones iniciadas con la app 2026.11.20.8 o posterior. "
                        "Última versión con que cada usuario registró un error (7 días): "
                        + (", ".join(f"{x.get('usuario')} {x.get('version') or '-'}" for x in vers_err[:12]) or "-"),
                        size=11, color=INK_3),
            ], spacing=8), col={"xs": 12})

        top = supabase.table("wms_errores_grupos").select("*").in_("estado", ["NUEVO", "REAPARECIO", "EN_REVISION"]) \
            .order("ultima_vez", desc=True).limit(6).execute().data or []
        card_top = _tarjeta("Para revisar ahora", "Errores pendientes más recientes (clic para ver el detalle)", ft.Column(
            [self._fila_error_compacta(g) for g in top] or [_vacio("Nada pendiente. ✔")], spacing=6),
            col={"xs": 12, "lg": 6})
        tks = supabase.table("wms_tickets").select("*").in_("estado", ["NUEVO", "EN_REVISION", "EN_DESARROLLO"]) \
            .order("id", desc=True).limit(6).execute().data or []
        card_tk = _tarjeta("Tickets abiertos", "Últimos reportes de usuarios", ft.Column(
            [self._fila_ticket_compacta(t) for t in tks] or [_vacio("Sin tickets abiertos.")], spacing=6),
            col={"xs": 12, "lg": 6})
        return [tiles, ft.ResponsiveRow([card_dias, card_mod], spacing=12, run_spacing=12),
                ft.ResponsiveRow([card_top, card_tk], spacing=12, run_spacing=12),
                ft.ResponsiveRow([card_ver], spacing=12)]

    def _fila_error_compacta(self, g):
        return ft.Container(
            padding=10, border_radius=8, bgcolor=UI["card_alt"], ink=True, on_click=lambda e: self._dialogo_error(g),
            content=ft.Row([
                _chip(EST_ERROR.get(g.get("estado"), EST_ERROR["NUEVO"])),
                ft.Text(str(g.get("mensaje") or "")[:110], size=12, color=INK, expand=True, max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{_miles(g.get('ocurrencias'))}×", size=12, color=INK_2),
            ], spacing=10))

    def _fila_ticket_compacta(self, t):
        return ft.Container(
            padding=10, border_radius=8, bgcolor=UI["card_alt"], ink=True, on_click=lambda e: self._dialogo_ticket(t),
            content=ft.Row([
                _chip(PRIORIDAD.get(t.get("prioridad"), PRIORIDAD["MEDIA"])),
                ft.Text(f"#{t.get('id')} {t.get('titulo')}", size=12, color=INK, expand=True, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{t.get('usuario') or '-'} · {formatear_fecha_hora_chile(t.get('creado_en'))}", size=11, color=INK_2),
            ], spacing=10))

    # ------------------------------------------------------------- 1 Errores
    def _vista_errores(self):
        q = supabase.table("wms_errores_grupos").select("*")
        if self.filtro_err == "PENDIENTES":
            q = q.in_("estado", ["NUEVO", "REAPARECIO", "EN_REVISION"])
        elif self.filtro_err != "TODOS":
            q = q.eq("estado", self.filtro_err)
        if self.filtro_origen != "TODOS":
            q = q.eq("origen", self.filtro_origen)
        grupos = q.order("ultima_vez", desc=True).limit(400).execute().data or []
        b = (self.txt_buscar.value or "").strip().upper()
        if b:
            grupos = [g for g in grupos if b in f"{g.get('mensaje')} {g.get('modulo')} {g.get('nota') or ''}".upper()]

        filas = []
        for g in grupos:
            filas.append(ft.DataRow(
                on_select_change=lambda e, x=g: self._dialogo_error(x),
                cells=[
                    ft.DataCell(_chip(EST_ERROR.get(g.get("estado"), EST_ERROR["NUEVO"]))),
                    ft.DataCell(_t("Celular" if g.get("origen") == "RF" else "PC", color=INK_2)),
                    ft.DataCell(_t(g.get("modulo") or "-", color=INK_2)),
                    ft.DataCell(ft.Container(width=460, content=ft.Text(
                        str(g.get("mensaje") or ""), size=12, color=INK, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                        tooltip=str(g.get("mensaje") or "")[:600]))),
                    ft.DataCell(_t(_miles(g.get("ocurrencias")), ft.FontWeight.W_600)),
                    ft.DataCell(_t(formatear_fecha_hora_chile(g.get("ultima_vez")), color=INK_2)),
                    ft.DataCell(_t(g.get("ultima_version") or "-", color=INK_2)),
                    ft.DataCell(_t(f"#{g.get('ticket_id')}" if g.get("ticket_id") else "", color=UI["acento"])),
                ]))
        tabla = ft.DataTable(columns=[_col("Estado"), _col("Origen"), _col("Módulo"), _col("Mensaje"),
                                      _col("Veces", True), _col("Última vez"), _col("Versión"), _col("Ticket")],
                             rows=filas, show_checkbox_column=False)

        def elegir_estado(x):
            self.filtro_err = x
            self._construir()

        def elegir_origen(x):
            self.filtro_origen = x
            self._construir()

        filtros = ft.Column([
            _filtros([("PENDIENTES", "Por revisar"), ("NUEVO", "Nuevos"), ("REAPARECIO", "Reaparecidos"),
                      ("EN_REVISION", "En revisión"), ("RESUELTO", "Resueltos"), ("IGNORADO", "Ignorados"),
                      ("TODOS", "Todos")], self.filtro_err, elegir_estado),
            ft.Row([_filtros([("TODOS", "Celular y PC"), ("RF", "Celular"), ("PC", "PC")], self.filtro_origen, elegir_origen),
                    self.txt_buscar, ui_boton("Buscar", ft.Icons.SEARCH_ROUNDED, lambda e: self._construir(), "texto")],
                   spacing=12, wrap=True, run_spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=8)
        return [_tarjeta("Errores agrupados",
                         f"{len(grupos)} grupos · el mismo error se agrupa aunque cambie un número (LPN, id, hora). "
                         "Clic en una fila para ver el detalle y cambiar su estado.",
                         ft.Column([filtros, ui_tabla(tabla, 560) if filas else _vacio("No hay errores con este filtro.")],
                                   spacing=12))]

    def _dialogo_error(self, g):
        page = self.page
        try:
            ocur = supabase.table("wms_log_errores").select("*").eq("firma", g["firma"]) \
                .order("id", desc=True).limit(60).execute().data or []
        except Exception as ex:
            notificar_global(page, f"No se pudo leer el detalle: {_msg_error(ex)}", "#B45309")
            return
        usuarios = sorted({str(o.get("usuario") or "-") for o in ocur})
        detalle = next((o.get("detalle") for o in ocur if o.get("detalle")), "") or ""
        txt_nota = _campo("Nota (causa, solución, script que lo arregla…)", g.get("nota") or "", ancho=640, multilinea=True)
        lbl_err = ft.Text("", size=12, color="#F87171")

        tabla = ft.DataTable(columns=[_col("Fecha"), _col("Usuario"), _col("Módulo"), _col("Versión"), _col("Bodega")], rows=[
            ft.DataRow(cells=[ft.DataCell(_t(formatear_fecha_hora_chile(o.get("creado_en")), size=11.5)),
                              ft.DataCell(_t(o.get("usuario") or "-", size=11.5)),
                              ft.DataCell(_t(o.get("modulo") or "-", size=11.5, color=INK_2)),
                              ft.DataCell(_t(o.get("version_app") or "-", size=11.5, color=INK_2)),
                              ft.DataCell(_t(o.get("bodega") or "-", size=11.5, color=INK_2))]) for o in ocur])

        def guardar(estado=None):
            datos = {"nota": (txt_nota.value or "").strip() or None, "actualizado_por": _usuario(page),
                     "actualizado_en": datetime.now(timezone.utc).isoformat()}
            if estado:
                datos["estado"] = estado
                if estado == "RESUELTO":
                    datos["resuelto_en"] = datetime.now(timezone.utc).isoformat()
            try:
                supabase.table("wms_errores_grupos").update(datos).eq("firma", g["firma"]).execute()
            except Exception as ex:
                lbl_err.value = f"No se guardó: {_msg_error(ex)}"
                page.update()
                return
            _cerrar(page)
            notificar_global(page, "Error actualizado.", "#047857")
            self._construir()

        def crear_ticket(e=None):
            try:
                r = supabase.rpc("wms_reportar_problema", {
                    "p_origen": "DEV", "p_modulo": g.get("modulo"), "p_tipo": "ERROR",
                    "p_titulo": str(g.get("mensaje") or "Error")[:120],
                    "p_descripcion": f"Creado desde el error agrupado ({_miles(g.get('ocurrencias'))} veces, "
                                     f"usuarios: {', '.join(usuarios[:10])}).\n\n{g.get('mensaje')}",
                    "p_usuario": _usuario(page), "p_bodega": None, "p_version": g.get("ultima_version"),
                    "p_dispositivo": "PC", "p_prioridad": "ALTA",
                }).execute().data or {}
                tid = r.get("id")
                supabase.table("wms_tickets").update({"firma_error": g["firma"]}).eq("id", tid).execute()
                supabase.table("wms_errores_grupos").update({"ticket_id": tid, "estado": "EN_REVISION",
                                                              "actualizado_por": _usuario(page)}).eq("firma", g["firma"]).execute()
            except Exception as ex:
                lbl_err.value = f"No se creó el ticket: {_msg_error(ex)}"
                page.update()
                return
            _cerrar(page)
            notificar_global(page, f"Ticket #{tid} creado y enlazado al error.", "#047857")
            self._construir()

        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Row([_chip(EST_ERROR.get(g.get("estado"), EST_ERROR["NUEVO"])),
                          ft.Text(f"{'Celular' if g.get('origen') == 'RF' else 'PC'} · {g.get('modulo') or '-'}",
                                  size=15, weight=ft.FontWeight.BOLD)], spacing=12),
            content=ft.Container(width=700, height=560, content=ft.Column([
                ft.Text(f"{_miles(g.get('ocurrencias'))} veces · primera {formatear_fecha_hora_chile(g.get('primera_vez'))} · "
                        f"última {formatear_fecha_hora_chile(g.get('ultima_vez'))} · versión {g.get('ultima_version') or '-'}",
                        size=11.5, color=INK_2),
                ft.Text(f"Usuarios afectados ({len(usuarios)}): {', '.join(usuarios[:20])}", size=11.5, color=INK_2),
                ft.Container(padding=10, border_radius=6, bgcolor=UI["card_alt"], border=ft.Border.all(1, UI["borde"]),
                             content=ft.Text(str(g.get("mensaje") or ""), size=12, color=INK, selectable=True,
                                             font_family="Consolas")),
                *([ft.Text("Detalle técnico (último con traza)", size=11.5, color=INK_2),
                   ft.Container(padding=10, border_radius=6, bgcolor=UI["card_alt"], height=150,
                                content=ft.Column([ft.Text(detalle[:4000], size=11, color=INK_2, selectable=True,
                                                           font_family="Consolas")], scroll=ft.ScrollMode.AUTO))]
                  if detalle else []),
                txt_nota,
                ft.Text("Ocurrencias recientes", size=11.5, color=INK_2),
                ui_tabla(tabla, 200),
                lbl_err,
            ], spacing=10, scroll=ft.ScrollMode.AUTO)),
            actions=[
                *([] if g.get("ticket_id") else [ui_boton("Crear ticket", ft.Icons.CONFIRMATION_NUMBER_OUTLINED, crear_ticket, "texto")]),
                ui_boton("Ignorar", ft.Icons.VISIBILITY_OFF_OUTLINED, lambda e: guardar("IGNORADO"), "texto",
                         tooltip="No es un problema real (validación, red caída…). No vuelve a aparecer como pendiente."),
                ui_boton("En revisión", ft.Icons.MANAGE_SEARCH_ROUNDED, lambda e: guardar("EN_REVISION"), "secundario"),
                ui_boton("Marcar resuelto", ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED, lambda e: guardar("RESUELTO"), "primario",
                         tooltip="Si vuelve a ocurrir, pasa solo a 'Reapareció'."),
                ui_boton("Cerrar", None, lambda e: _cerrar(page), "texto"),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        ))

    # ------------------------------------------------------------- 2 Tickets
    def _vista_tickets(self):
        q = supabase.table("wms_tickets").select("*")
        if self.filtro_tk == "ABIERTOS":
            q = q.in_("estado", ["NUEVO", "EN_REVISION", "EN_DESARROLLO"])
        elif self.filtro_tk != "TODOS":
            q = q.eq("estado", self.filtro_tk)
        tks = q.order("id", desc=True).limit(400).execute().data or []
        b = (self.txt_buscar.value or "").strip().upper()
        if b:
            tks = [t for t in tks if b in f"{t.get('titulo')} {t.get('descripcion') or ''} {t.get('usuario')} {t.get('modulo')}".upper()]
        orden_p = {"CRITICA": 0, "ALTA": 1, "MEDIA": 2, "BAJA": 3}
        if self.filtro_tk == "ABIERTOS":
            tks.sort(key=lambda t: (orden_p.get(t.get("prioridad"), 2), -int(t.get("id") or 0)))
        filas = [ft.DataRow(
            on_select_change=lambda e, x=t: self._dialogo_ticket(x),
            cells=[
                ft.DataCell(_t(f"#{t.get('id')}", ft.FontWeight.W_600, UI["acento"])),
                ft.DataCell(_chip(PRIORIDAD.get(t.get("prioridad"), PRIORIDAD["MEDIA"]))),
                ft.DataCell(_chip(EST_TICKET.get(t.get("estado"), EST_TICKET["NUEVO"]))),
                ft.DataCell(_t(TIPOS.get(t.get("tipo"), t.get("tipo")), color=INK_2)),
                ft.DataCell(ft.Container(width=360, content=ft.Text(str(t.get("titulo") or ""), size=12, color=INK, max_lines=2,
                                                                    overflow=ft.TextOverflow.ELLIPSIS))),
                ft.DataCell(_t(t.get("usuario") or "-")),
                ft.DataCell(_t(f"{'Celular' if t.get('origen') == 'RF' else t.get('origen')} · {t.get('modulo') or '-'}", color=INK_2)),
                ft.DataCell(_t(formatear_fecha_hora_chile(t.get("creado_en")), color=INK_2)),
            ]) for t in tks]
        tabla = ft.DataTable(columns=[_col("N°"), _col("Prioridad"), _col("Estado"), _col("Tipo"), _col("Título"),
                                      _col("Usuario"), _col("Dónde"), _col("Creado")], rows=filas, show_checkbox_column=False)

        def elegir(x):
            self.filtro_tk = x
            self._construir()

        nuevo = ui_boton("Nuevo ticket", ft.Icons.ADD_ROUNDED, lambda e: abrir_reportar_problema(self.page, "Desarrollador"),
                         "secundario")
        return [_tarjeta("Tickets", f"{len(tks)} tickets · clic en una fila para gestionarlo", ft.Column([
            ft.Row([_filtros([("ABIERTOS", "Abiertos"), ("NUEVO", "Nuevos"), ("EN_REVISION", "En revisión"),
                              ("EN_DESARROLLO", "En desarrollo"), ("RESUELTO", "Resueltos"), ("DESCARTADO", "Descartados"),
                              ("TODOS", "Todos")], self.filtro_tk, elegir),
                    self.txt_buscar, ui_boton("Buscar", ft.Icons.SEARCH_ROUNDED, lambda e: self._construir(), "texto")],
                   spacing=12, wrap=True, run_spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ui_tabla(tabla, 560) if filas else _vacio("No hay tickets con este filtro."),
        ], spacing=12), accion=nuevo)]

    def _dialogo_ticket(self, t):
        page = self.page
        try:
            coms = supabase.table("wms_tickets_comentarios").select("*").eq("ticket_id", t["id"]).order("id").execute().data or []
            cercanos = []
            if t.get("usuario") and t.get("creado_en"):
                base = datetime.fromisoformat(str(t["creado_en"]).replace("Z", "+00:00"))
                cercanos = supabase.table("wms_log_errores").select("creado_en, modulo, mensaje, version_app") \
                    .eq("usuario", t["usuario"]).gte("creado_en", (base - timedelta(minutes=60)).isoformat()) \
                    .lte("creado_en", (base + timedelta(minutes=10)).isoformat()).order("id", desc=True).limit(10).execute().data or []
        except Exception as ex:
            notificar_global(page, f"No se pudo leer el ticket: {_msg_error(ex)}", "#B45309")
            return
        dd_estado = _dropdown("Estado", {k: v[0] for k, v in EST_TICKET.items()}, t.get("estado") or "NUEVO", 190)
        dd_prio = _dropdown("Prioridad", {k: v[0] for k, v in PRIORIDAD.items()}, t.get("prioridad") or "MEDIA", 150)
        txt_resp = _campo("Respuesta para el usuario (la ve en 'Mis reportes')", t.get("respuesta") or "", ancho=660, multilinea=True)
        txt_com = _campo("Agregar comentario", ancho=520)
        chk_visible = ft.Checkbox(label="Visible para el usuario", value=False, label_style=ft.TextStyle(size=11.5, color=INK))
        lbl_err = ft.Text("", size=12, color="#F87171")
        lista_com = ft.Column([
            ft.Container(padding=8, border_radius=6, bgcolor=UI["card_alt"], content=ft.Column([
                ft.Text(f"{formatear_fecha_hora_chile(c.get('creado_en'))} · {c.get('usuario') or ''}"
                        + ("" if c.get("interno") else " · visible para el usuario"), size=10.5, color=INK_3),
                ft.Text(c.get("texto") or "", size=12, color=INK, selectable=True)], spacing=2, tight=True))
            for c in coms] or [ft.Text("Sin comentarios.", size=11.5, color=INK_3)], spacing=6)

        def guardar(e=None):
            ahora = datetime.now(timezone.utc).isoformat()
            datos = {"estado": dd_estado.value, "prioridad": dd_prio.value,
                     "respuesta": (txt_resp.value or "").strip() or None, "actualizado_en": ahora}
            if dd_estado.value in ("RESUELTO", "DESCARTADO") and not t.get("resuelto_en"):
                datos["resuelto_en"] = ahora
            try:
                supabase.table("wms_tickets").update(datos).eq("id", t["id"]).execute()
                if (txt_com.value or "").strip():
                    supabase.table("wms_tickets_comentarios").insert({
                        "ticket_id": t["id"], "usuario": _usuario(page), "texto": txt_com.value.strip(),
                        "interno": not chk_visible.value}).execute()
                if t.get("firma_error") and dd_estado.value == "RESUELTO":
                    supabase.table("wms_errores_grupos").update({"estado": "RESUELTO", "resuelto_en": ahora,
                                                                  "actualizado_por": _usuario(page)}) \
                        .eq("firma", t["firma_error"]).execute()
            except Exception as ex:
                lbl_err.value = f"No se guardó: {_msg_error(ex)}"
                page.update()
                return
            _cerrar(page)
            notificar_global(page, f"Ticket #{t['id']} actualizado.", "#047857")
            self._construir()

        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text(f"#{t.get('id')} · {t.get('titulo')}", size=15, weight=ft.FontWeight.BOLD),
            content=ft.Container(width=700, height=560, content=ft.Column([
                ft.Text(f"{TIPOS.get(t.get('tipo'), t.get('tipo'))} · {t.get('usuario') or '-'} · {t.get('bodega') or '-'} · "
                        f"{'Celular' if t.get('origen') == 'RF' else t.get('origen')} · {t.get('modulo') or '-'} · "
                        f"versión {t.get('version_app') or '-'} · {formatear_fecha_hora_chile(t.get('creado_en'))}",
                        size=11.5, color=INK_2),
                ft.Container(padding=10, border_radius=6, bgcolor=UI["card_alt"], border=ft.Border.all(1, UI["borde"]),
                             content=ft.Text(t.get("descripcion") or "(sin detalle)", size=12.5, color=INK, selectable=True)),
                *([ft.Text("Errores registrados de este usuario cerca del reporte", size=11.5, color=INK_2),
                   ft.Column([ft.Text(f"{formatear_fecha_hora_chile(x.get('creado_en'))} · {x.get('modulo') or '-'} · "
                                      f"{str(x.get('mensaje') or '')[:200]}", size=11.5, color=ESTADO['serio'], selectable=True)
                              for x in cercanos], spacing=4)] if cercanos else []),
                ft.Row([dd_estado, dd_prio], spacing=10),
                txt_resp,
                ft.Text("Comentarios", size=11.5, color=INK_2),
                lista_com,
                ft.Row([txt_com, chk_visible], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                lbl_err,
            ], spacing=10, scroll=ft.ScrollMode.AUTO)),
            actions=[ui_boton("Cancelar", None, lambda e: _cerrar(page), "texto"),
                     ui_boton("Guardar", ft.Icons.SAVE_ROUNDED, guardar, "primario")],
            actions_alignment=ft.MainAxisAlignment.END,
        ))
