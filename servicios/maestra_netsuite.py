"""Traer artículos de NetSuite a la maestra del WMS (maestra_sku).

NetSuite tiene el código (itemid), el nombre, el código de barras (UPC) y la unidad de compra con su
factor (ej. "Caja 48" = 48 unidades). Con eso se crean en la maestra:
  · una fila UNIDAD (código de barras = UPC, o el SKU si no tiene), con el peso si viene;
  · una fila CAJA si la unidad de compra de NetSuite trae más de 1 unidad.
Solo CREA lo que falta: nunca cambia un SKU que ya está en la maestra.
"""
import re

_COLS_COMPLETAS = """
    i.id AS ns_id, i.itemid AS sku, i.displayname AS nombre, i.purchasedescription AS descripcion_compra,
    i.upccode AS upc, i.weight AS peso, BUILTIN.DF(i.weightunit) AS peso_unidad,
    BUILTIN.DF(i.purchaseunit) AS unidad_compra, u.conversionrate AS factor_compra, i.isinactive AS inactivo
"""
_FROM_COMPLETO = "FROM item i LEFT JOIN unitstypeuom u ON u.internalid = i.purchaseunit"
_COLS_SIMPLES = "i.id AS ns_id, i.itemid AS sku, i.displayname AS nombre, i.upccode AS upc"


def _sql_texto(s: str) -> str:
    return str(s or "").replace("'", "''").strip().upper()


def _consultar_items(consultar, filtro: str):
    for cols, origen in ((_COLS_COMPLETAS, _FROM_COMPLETO), (_COLS_SIMPLES, "FROM item i")):
        df = consultar(f"SELECT {cols} {origen} WHERE {filtro} ORDER BY i.itemid")
        if df is not None:
            return df
    return None


def _valor(v):
    if v is None:
        return None
    try:
        if v != v:          # NaN
            return None
    except Exception:
        pass
    t = str(v).strip()
    return None if t.lower() in ("", "nan", "none", "null") else t


def buscar_items_netsuite(consultar, skus=None, texto=None, limite=60) -> list:
    """Artículos de NetSuite por lista de SKU exactos o por texto (código o nombre)."""
    filas = []
    if skus:
        lista = sorted({_sql_texto(s) for s in skus if _sql_texto(s)})
        for i in range(0, len(lista), 150):
            parte = ",".join(f"'{s}'" for s in lista[i:i + 150])
            df = _consultar_items(consultar, f"UPPER(i.itemid) IN ({parte})")
            if df is None:
                raise RuntimeError("NetSuite no respondió a la búsqueda de artículos")
            filas += df.to_dict("records")
    elif texto:
        t = _sql_texto(texto)
        df = _consultar_items(consultar, f"(UPPER(i.itemid) LIKE '%{t}%' OR UPPER(i.displayname) LIKE '%{t}%' "
                                         f"OR i.upccode = '{t}')")
        if df is None:
            raise RuntimeError("NetSuite no respondió a la búsqueda de artículos")
        filas = df.to_dict("records")[:limite]
    out = []
    for f in filas:
        sku = (_valor(f.get("sku")) or "").upper()
        if not sku:
            continue
        # itemid de artículos con padre viene como "PADRE : HIJO"
        sku = sku.split(":")[-1].strip()
        try:
            factor = float(_valor(f.get("factor_compra")) or 1)
        except ValueError:
            factor = 1.0
        try:
            peso = float(_valor(f.get("peso")) or 0)
        except ValueError:
            peso = 0.0
        unidad_peso = (_valor(f.get("peso_unidad")) or "kg").lower()
        if peso and unidad_peso.startswith("g") and not unidad_peso.startswith("gal"):
            peso = peso / 1000.0
        elif peso and unidad_peso.startswith("lb"):
            peso = peso * 0.453592
        out.append({
            "ns_id": _valor(f.get("ns_id")), "sku": sku,
            "descripcion": _valor(f.get("nombre")) or _valor(f.get("descripcion_compra")) or sku,
            "upc": _valor(f.get("upc")), "unidad_compra": _valor(f.get("unidad_compra")),
            "factor_compra": int(round(factor)) if factor and factor > 0 else 1,
            "peso_kg": round(peso, 4) if peso else None,
            "inactivo": str(_valor(f.get("inactivo")) or "F").upper() in ("T", "TRUE"),
        })
    return out


def filas_maestra(item: dict, marca: str = None) -> list:
    """Filas a crear en maestra_sku para un artículo de NetSuite."""
    sku = item["sku"]
    base = {"sku": sku, "descripcion": item["descripcion"], "marca": (marca or "ESTANDAR").upper(), "activo": True}
    cb_unidad = re.sub(r"\s+", "", item.get("upc") or "") or sku
    filas = [{**base, "codigo_barras": cb_unidad, "multiplo": 1, "unidad_medida": "UNIDAD",
              **({"peso_kg": item["peso_kg"]} if item.get("peso_kg") else {})}]
    if (item.get("factor_compra") or 1) > 1:
        filas.append({**base, "codigo_barras": sku, "multiplo": int(item["factor_compra"]), "unidad_medida": "CAJA",
                      **({"peso_kg": round(item["peso_kg"] * item["factor_compra"], 3)} if item.get("peso_kg") else {})})
    return filas


def skus_que_faltan(supabase, skus) -> list:
    lista = sorted({str(s or "").strip().upper() for s in skus if str(s or "").strip()})
    existentes = set()
    for i in range(0, len(lista), 150):
        res = supabase.table("maestra_sku").select("sku").in_("sku", lista[i:i + 150]).execute().data or []
        existentes |= {str(r.get("sku") or "").strip().upper() for r in res}
    return [s for s in lista if s not in existentes]


def crear_en_maestra(supabase, items: list, marca: str = None) -> int:
    """Crea en la maestra los artículos que todavía no están. Devuelve cuántos SKU se crearon."""
    faltan = set(skus_que_faltan(supabase, [it["sku"] for it in items]))
    creados = 0
    for it in items:
        if it["sku"] not in faltan:
            continue
        filas = filas_maestra(it, marca)
        try:
            supabase.table("maestra_sku").insert(filas).execute()
        except Exception as ex:
            if "peso_kg" in str(ex):        # maestra sin columna de peso
                supabase.table("maestra_sku").insert([{k: v for k, v in f.items() if k != "peso_kg"} for f in filas]).execute()
            else:
                raise
        creados += 1
        faltan.discard(it["sku"])
    return creados


def completar_skus_desde_netsuite(supabase, consultar, skus, marca: str = None) -> dict:
    """Busca en NetSuite los SKU que no están en la maestra y los crea. {creados, no_encontrados}."""
    faltan = skus_que_faltan(supabase, skus)
    if not faltan:
        return {"creados": 0, "faltaban": 0, "no_encontrados": []}
    items = buscar_items_netsuite(consultar, skus=faltan)
    creados = crear_en_maestra(supabase, items, marca)
    encontrados = {it["sku"] for it in items}
    return {"creados": creados, "faltaban": len(faltan), "no_encontrados": [s for s in faltan if s not in encontrados]}
