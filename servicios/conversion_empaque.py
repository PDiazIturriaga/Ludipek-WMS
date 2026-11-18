from dominio.modelos import CantidadEmpaque

def convertir_unidades(unidades: int, multiplo_caja: int, multiplo_display: int = 1) -> CantidadEmpaque:
    if unidades < 0:
        raise ValueError("Las unidades no pueden ser negativas")
    caja = max(1, int(multiplo_caja or 1))
    display = max(1, int(multiplo_display or 1))
    if display >= caja:
        display = 1
    cajas, resto = divmod(unidades, caja)
    displays, sueltas = divmod(resto, display)
    return CantidadEmpaque(cajas, displays, sueltas, caja, display)

def calcular_unidades(cajas: int, displays: int, sueltas: int, multiplo_caja: int, multiplo_display: int = 1) -> int:
    valores = (cajas, displays, sueltas, multiplo_caja, multiplo_display)
    if any(int(v or 0) < 0 for v in valores):
        raise ValueError("Cajas, displays, unidades y múltiplos deben ser no negativos")
    return int(cajas) * int(multiplo_caja) + int(displays) * int(multiplo_display) + int(sueltas)

def seleccionar_presentaciones(filas: list[dict]) -> dict:
    resultado = {"unidad": None, "display": None, "caja": None}
    for fila in filas:
        um = str(fila.get("unidad_medida") or "").upper().replace(" ", "_")
        if um in {"CAJA", "CAJA_MASTER", "MASTER", "CJ"}:
            resultado["caja"] = fila if resultado["caja"] is None or int(fila.get("multiplo") or 1) > int(resultado["caja"].get("multiplo") or 1) else resultado["caja"]
        elif um in {"DISPLAY", "DSP"}:
            resultado["display"] = fila
        elif um in {"UNIDAD", "UN", "UNIT"}:
            resultado["unidad"] = fila
    return resultado
