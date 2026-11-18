from collections import defaultdict
from datetime import date
from dominio.modelos import LineaConciliacion
from servicios.normalizacion import normalizar_sku, normalizar_lote, fecha_a_date

def _agrupar(lineas: list[dict], campo_cantidad: str):
    agrupado = defaultdict(int)
    descripciones = {}
    for linea in lineas:
        sku = normalizar_sku(linea.get("sku"))
        lote = normalizar_lote(linea.get("lote"))
        fecha = fecha_a_date(linea.get("fecha_vencimiento") or linea.get("fecha_vencimiento_cl"))
        clave = (sku, lote, fecha)
        agrupado[clave] += int(linea.get(campo_cantidad) or 0)
        descripciones[sku] = str(linea.get("descripcion") or "")
    return agrupado, descripciones

def conciliar(oc: list[dict], packing_list: list[dict], fisico: list[dict]) -> list[LineaConciliacion]:
    oc_a, desc_oc = _agrupar(oc, "unidades")
    pl_a, desc_pl = _agrupar(packing_list, "unidades")
    fi_a, desc_fi = _agrupar(fisico, "unidades")
    claves = sorted(set(oc_a) | set(pl_a) | set(fi_a), key=lambda x: (x[0], x[1], x[2] or date.min))
    salida = []
    for sku, lote, fecha in claves:
        linea = LineaConciliacion(
            sku=sku,
            descripcion=desc_oc.get(sku) or desc_pl.get(sku) or desc_fi.get(sku) or "",
            lote=lote,
            fecha_vencimiento=fecha,
            unidades_oc=oc_a.get((sku, lote, fecha), 0),
            unidades_packing_list=pl_a.get((sku, lote, fecha), 0),
            unidades_recibidas=fi_a.get((sku, lote, fecha), 0),
        )
        if linea.unidades_oc == 0 and linea.unidades_packing_list > 0:
            linea.observaciones.append("SKU_LOTE_NO_EXISTE_EN_OC")
        if linea.diferencia_oc_pl < 0:
            linea.observaciones.append("FALTANTE_EN_PACKING_LIST")
        elif linea.diferencia_oc_pl > 0:
            linea.observaciones.append("SOBRANTE_EN_PACKING_LIST")
        if linea.diferencia_pl_fisico < 0:
            linea.observaciones.append("FALTANTE_FISICO")
        elif linea.diferencia_pl_fisico > 0:
            linea.observaciones.append("SOBRANTE_FISICO")
        if lote == "S/L":
            linea.observaciones.append("SIN_LOTE")
        if fecha is None:
            linea.observaciones.append("SIN_VENCIMIENTO")
        salida.append(linea)
    return salida
