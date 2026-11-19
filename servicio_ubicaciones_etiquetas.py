"""Servicio autocontenido para ubicaciones a piso de Bodega Concepcion.
Compatible con: from servicio_ubicaciones_etiquetas import ...
"""
from dataclasses import dataclass
from pathlib import Path
import shutil
import qrcode
from fpdf import FPDF

@dataclass(frozen=True)
class UbicacionWms:
    codigo_ubicacion: str
    bodega: str
    zona: str
    letra: str
    columna: int
    nivel: int = 1
    tipo_ubicacion: str = "PISO"


def codigo_ubicacion(letra: str, columna: int, nivel: int = 1) -> str:
    columna = int(columna)
    if columna >= 5:
        return f"{columna:02d}"
    letra = str(letra or "").strip().upper()
    if not letra:
        raise ValueError("Las columnas 01 a 04 requieren letra")
    return f"{letra}-{columna:02d}"


def generar_ubicaciones_concepcion() -> list[UbicacionWms]:
    letras = {
        1: tuple("MKJIHGFEDCBA"),
        2: tuple("MKJIHGFEDCBA"),
        3: tuple("MKJIHGFEDCB"),
        4: tuple("MKJIHGFEDCB"),
    }
    salida = []
    for columna, grupos in letras.items():
        for letra in grupos:
            salida.append(UbicacionWms(
                codigo_ubicacion=f"{letra}-{columna:02d}",
                bodega="Bodega Concepcion",
                zona=f"COLUMNA {columna:02d}",
                letra=letra,
                columna=columna,
            ))
    for columna in range(5, 16):
        salida.append(UbicacionWms(
            codigo_ubicacion=f"{columna:02d}",
            bodega="Bodega Concepcion",
            zona=f"COLUMNA {columna:02d}",
            letra="",
            columna=columna,
        ))
    return salida


def subir_ubicaciones_supabase(supabase, ubicaciones, lote: int = 400) -> int:
    filas = [{
        "codigo_ubicacion": u.codigo_ubicacion,
        "zona": u.zona,
        "bodega": u.bodega,
    } for u in ubicaciones]
    for inicio in range(0, len(filas), lote):
        supabase.table("bodega_ubicaciones").upsert(
            filas[inicio:inicio + lote],
            on_conflict="bodega,codigo_ubicacion",
        ).execute()
    return len(filas)


def _qr(codigo: str, carpeta: Path) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{codigo}.png"
    qrcode.make(codigo).save(ruta)
    return ruta


def generar_pdfs_ubicaciones(ubicaciones, carpeta_salida: str, solo_pasillo=None, modo_nivel="PICKING") -> list[str]:
    salida = Path(carpeta_salida)
    salida.mkdir(parents=True, exist_ok=True)
    qr_dir = salida / "_qrs"
    filtro = str(solo_pasillo or "TODOS").upper()
    seleccion = list(ubicaciones)
    if filtro not in {"", "TODOS"}:
        seleccion = [u for u in seleccion if u.letra == filtro or f"{u.columna:02d}" == filtro]
    grupos = {}
    for u in seleccion:
        grupo = f"LETRA_{u.letra}" if u.letra else f"COLUMNA_{u.columna:02d}"
        grupos.setdefault(grupo, []).append(u)
    archivos = []
    for grupo, items in sorted(grupos.items()):
        pdf = FPDF(orientation="L", unit="mm", format=(100, 200))
        pdf.set_auto_page_break(False)
        for u in items:
            pdf.add_page()
            qr = _qr(u.codigo_ubicacion, qr_dir)
            pdf.set_font("Helvetica", "B", 27)
            pdf.set_xy(5, 14); pdf.cell(108, 12, "UBICACION", align="C")
            pdf.set_font("Helvetica", "B", 43)
            pdf.set_xy(5, 44); pdf.cell(108, 18, u.codigo_ubicacion, align="C")
            pdf.line(115, 7, 115, 79)
            pdf.image(str(qr), x=122, y=8, w=68)
            pdf.set_fill_color(30, 30, 30); pdf.rect(0, 86, 200, 14, style="F")
            pdf.set_text_color(255, 255, 255); pdf.set_font("Helvetica", "B", 14)
            pdf.set_xy(0, 90); pdf.cell(200, 6, f"LUDIPEK CCP - COLUMNA {u.columna:02d}", align="C")
            pdf.set_text_color(0, 0, 0); pdf.rect(.5, .5, 199, 99)
        ruta = salida / f"Etiquetas_CCP_{grupo}_PISO.pdf"
        pdf.output(str(ruta)); archivos.append(str(ruta))
    shutil.rmtree(qr_dir, ignore_errors=True)
    return archivos


# =====================================================================
# BODEGA SANTIAGO: racks (A-01-01 = rack A, columna 01, nivel 01) y arena
# (MK/ME/BE-fila-posición). Lee las ubicaciones reales de bodega_ubicaciones.
# =====================================================================
import re

_PAT_RACK = re.compile(r"^([A-Z])-(\d{2})-(\d{2})$")
_PAT_ARENA = re.compile(r"^(MK|ME|BE)-(\d{2})-(\d{2})$")
NOMBRE_ARENA = {"MK": "ARENA MARKETING", "ME": "MERMAS ARENA", "BE": "ARENA BODEGA E"}
# Color de la franja inferior: el operador distingue de lejos picking, reserva, arena y merma
_COLOR_PIE = {"PICKING": (4, 120, 87), "RESERVA": (30, 41, 59), "ARENA": (133, 92, 45), "MERMA": (153, 27, 27), "OTRA": (30, 30, 30)}


def describir_ubicacion_stgo(codigo: str) -> dict:
    cod = str(codigo or "").strip().upper()
    m = _PAT_RACK.match(cod)
    if m:
        letra, col, niv = m.group(1), int(m.group(2)), int(m.group(3))
        tipo = "PICKING" if niv == 1 else "RESERVA"
        return {"codigo": cod, "grupo": f"RACK_{letra}", "zona": f"RACK {letra}", "tipo": tipo, "letra": letra,
                "columna": col, "nivel": niv,
                "pie": f"RACK {letra} · COL {col:02d} · NIVEL {niv:02d} · {'PICKING' if niv == 1 else 'RESERVA'}"}
    m = _PAT_ARENA.match(cod)
    if m:
        zona, fila, posn = m.group(1), int(m.group(2)), int(m.group(3))
        return {"codigo": cod, "grupo": f"ARENA_{zona}", "zona": NOMBRE_ARENA[zona], "tipo": "MERMA" if zona == "ME" else "ARENA",
                "letra": zona, "columna": fila, "nivel": posn,
                "pie": f"{NOMBRE_ARENA[zona]} · FILA {fila:02d} · POSICION {posn:02d}"}
    return {"codigo": cod, "grupo": "OTRAS", "zona": "OTRAS", "tipo": "OTRA", "letra": "", "columna": 0, "nivel": 0,
            "pie": "BODEGA SANTIAGO"}


def generar_pdfs_ubicaciones_stgo(codigos, carpeta_salida: str) -> list[str]:
    """Una etiqueta 200 x 100 mm por ubicación (código grande + QR), un PDF por rack / zona de arena."""
    salida = Path(carpeta_salida)
    salida.mkdir(parents=True, exist_ok=True)
    qr_dir = salida / "_qrs"
    grupos = {}
    for c in codigos:
        d = describir_ubicacion_stgo(c)
        grupos.setdefault(d["grupo"], []).append(d)
    archivos = []
    for grupo, items in sorted(grupos.items()):
        items.sort(key=lambda d: (d["columna"], d["nivel"], d["codigo"]))
        pdf = FPDF(orientation="L", unit="mm", format=(100, 200))
        pdf.set_auto_page_break(False)
        for d in items:
            pdf.add_page()
            qr = _qr(d["codigo"], qr_dir)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "B", 24)
            pdf.set_xy(5, 12); pdf.cell(108, 12, "UBICACION", align="C")
            tam = 46
            pdf.set_font("Helvetica", "B", tam)
            while pdf.get_string_width(d["codigo"]) > 104 and tam > 24:
                tam -= 2
                pdf.set_font("Helvetica", "B", tam)
            pdf.set_xy(5, 40); pdf.cell(108, 20, d["codigo"], align="C")
            if d["tipo"] in ("PICKING", "RESERVA"):
                pdf.set_font("Helvetica", "B", 15)
                pdf.set_xy(5, 64); pdf.cell(108, 8, "NIVEL PICKING" if d["tipo"] == "PICKING" else f"RESERVA NIVEL {d['nivel']:02d}", align="C")
            pdf.line(115, 7, 115, 79)
            pdf.image(str(qr), x=122, y=8, w=68)
            r, g, b = _COLOR_PIE.get(d["tipo"], _COLOR_PIE["OTRA"])
            pdf.set_fill_color(r, g, b); pdf.rect(0, 86, 200, 14, style="F")
            pdf.set_text_color(255, 255, 255); pdf.set_font("Helvetica", "B", 13)
            pdf.set_xy(0, 90); pdf.cell(200, 6, f"LUDIPEK STGO - {d['pie']}", align="C")
            pdf.set_text_color(0, 0, 0); pdf.rect(.5, .5, 199, 99)
        ruta = salida / f"Etiquetas_STGO_{grupo}.pdf"
        pdf.output(str(ruta)); archivos.append(str(ruta))
    shutil.rmtree(qr_dir, ignore_errors=True)
    return archivos
