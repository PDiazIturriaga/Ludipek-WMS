import re
from datetime import date, datetime

FORMATOS_FECHA = (
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d",
)

def normalizar_sku(valor) -> str:
    texto = str(valor or "").strip().upper()
    return texto.removesuffix("-FA").strip()

def normalizar_lote(valor) -> str:
    texto = re.sub(r"\s+", "", str(valor or "").upper())
    return "S/L" if texto in {"", "SL", "S/L", "SINLOTE", "NONE", "NULL", "-"} else str(valor).strip().upper()

def fecha_a_date(valor) -> date | None:
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    texto = str(valor or "").strip()
    if texto.upper().replace(" ", "") in {"", "SF", "S/F", "SINFECHA", "NONE", "NULL", "-"}:
        return None
    texto = texto[:10]
    for formato in FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha no reconocida: {valor}")

def fecha_a_iso(valor) -> str | None:
    fecha = fecha_a_date(valor)
    return fecha.isoformat() if fecha else None

def fecha_a_visual(valor) -> str:
    fecha = fecha_a_date(valor)
    return fecha.strftime("%d/%m/%Y") if fecha else "S/F"

def lote_fecha_visual(lote, fecha) -> str:
    return f"{normalizar_lote(lote)} / {fecha_a_visual(fecha)}"

def normalizar_bodega(valor) -> str:
    texto = str(valor or "").strip().upper().replace("Ó", "O")
    if "CONCEPCION" in texto:
        return "BODEGA CONCEPCION"
    if "SANTIAGO" in texto:
        return "BODEGA SANTIAGO"
    return texto
