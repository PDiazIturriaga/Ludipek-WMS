"""Respaldo de TODOS los datos de Supabase a un archivo .zip en el PC (script 35).

Cada tabla del esquema public se descarga por lotes (wms_respaldo_lote) y se guarda como CSV
dentro del zip, junto a un manifiesto con la cantidad de filas de cada tabla. Los zip quedan en
la carpeta "respaldos" junto al programa (si esa carpeta está en OneDrive, quedan también en la
nube) y se conservan los últimos 30.

Uso:
  · Desde el PC: Desarrollador > Respaldos > "Respaldar ahora".
  · Programado (sin abrir pantallas):  python main.py --respaldo   (o WMS.exe --respaldo)
    Con la llave pública, el respaldo programado necesita en el .env:
        WMS_RESPALDO_USUARIO=...   WMS_RESPALDO_CLAVE=...
    (un usuario ADMIN o con el permiso PC_DESARROLLADOR).
"""
import csv
import io
import json
import os
import socket
import time
import zipfile
from datetime import datetime

CARPETA_RESPALDOS = os.path.abspath("respaldos")
CONSERVAR = 30
LOTE = 3000


def _valor_csv(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def ejecutar_respaldo(supabase, usuario: str = "", ambiente: str = "PRODUCCION", progreso=None,
                      carpeta: str = None) -> dict:
    """Descarga todo y escribe el zip. progreso(texto, fraccion) se llama durante el proceso."""
    carpeta = carpeta or CARPETA_RESPALDOS
    os.makedirs(carpeta, exist_ok=True)
    inicio = time.time()

    def avisar(txt, frac):
        if progreso:
            try:
                progreso(txt, frac)
            except Exception:
                pass

    tablas = supabase.rpc("wms_respaldo_tablas", {}).execute().data or []
    total_bytes = sum(int(t.get("bytes") or 0) for t in tablas) or 1
    hecho_bytes = 0
    sello = datetime.now().strftime("%Y%m%d_%H%M")
    sufijo = "_PRUEBAS" if ambiente == "PRUEBAS" else ""
    ruta = os.path.join(carpeta, f"WMS_respaldo_{sello}{sufijo}.zip")
    manifiesto = {"fecha": datetime.now().isoformat(timespec="seconds"), "ambiente": ambiente, "usuario": usuario,
                  "equipo": socket.gethostname(), "tablas": {}, "errores": {}}
    filas_total = 0

    tmp = ruta + ".parcial"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for t in tablas:
            nombre = t["tabla"]
            avisar(f"Respaldando {nombre}…", hecho_bytes / total_bytes)
            try:
                buf = io.StringIO()
                escritor = None
                columnas = None
                desde = None
                n = 0
                while True:
                    r = supabase.rpc("wms_respaldo_lote", {"p_tabla": nombre, "p_desde": desde, "p_limite": LOTE}).execute().data or {}
                    filas = r.get("filas") or []
                    if not filas:
                        break
                    if escritor is None:
                        columnas = list(filas[0].keys())
                        escritor = csv.writer(buf)
                        escritor.writerow(columnas)
                    for f in filas:
                        escritor.writerow([_valor_csv(f.get(c)) for c in columnas])
                    n += len(filas)
                    desde = r.get("ultimo")
                    if len(filas) < LOTE or not desde:
                        break
                    avisar(f"Respaldando {nombre}… {n:,} filas".replace(",", "."), hecho_bytes / total_bytes)
                zf.writestr(f"{nombre}.csv", buf.getvalue().encode("utf-8-sig"))
                manifiesto["tablas"][nombre] = n
                filas_total += n
            except Exception as ex:
                manifiesto["errores"][nombre] = str(getattr(ex, "message", None) or ex)[:300]
            hecho_bytes += int(t.get("bytes") or 0)
        manifiesto["segundos"] = round(time.time() - inicio, 1)
        manifiesto["filas_total"] = filas_total
        zf.writestr("manifiesto.json", json.dumps(manifiesto, ensure_ascii=False, indent=2))
    os.replace(tmp, ruta)
    peso = os.path.getsize(ruta)

    # Conservar solo los últimos N respaldos
    try:
        zips = sorted(f for f in os.listdir(carpeta) if f.startswith("WMS_respaldo_") and f.endswith(".zip"))
        for viejo in zips[:-CONSERVAR]:
            os.remove(os.path.join(carpeta, viejo))
    except Exception:
        pass

    estado = "OK" if not manifiesto["errores"] else "PARCIAL"
    try:
        supabase.table("wms_respaldos").insert({
            "usuario": usuario or None, "equipo": socket.gethostname()[:80], "estado": estado,
            "tablas": len(manifiesto["tablas"]), "filas": filas_total, "bytes": peso, "archivo": os.path.basename(ruta),
            "detalle": {"errores": manifiesto["errores"], "segundos": manifiesto["segundos"]},
        }).execute()
    except Exception:
        pass
    avisar("Respaldo terminado.", 1.0)
    return {"ruta": ruta, "estado": estado, "tablas": len(manifiesto["tablas"]), "filas": filas_total,
            "bytes": peso, "errores": manifiesto["errores"], "segundos": manifiesto["segundos"]}


def respaldo_programado() -> int:
    """Modo sin pantallas (python main.py --respaldo). Devuelve código de salida."""
    import dependencias as d
    usuario = os.getenv("WMS_RESPALDO_USUARIO", "").strip() or "RESPALDO_PROGRAMADO"
    try:
        if d.MODO_CONEXION_PC == "SESION":
            clave = os.getenv("WMS_RESPALDO_CLAVE", "").strip()
            if not os.getenv("WMS_RESPALDO_USUARIO") or not clave:
                print("[RESPALDO] Con la llave pública defina WMS_RESPALDO_USUARIO y WMS_RESPALDO_CLAVE en el .env")
                return 2
            u = d.iniciar_sesion_pc(usuario.upper(), clave, None)
            if not u or u.get("error"):
                print("[RESPALDO] Usuario o clave de respaldo incorrectos.")
                return 2
        res = ejecutar_respaldo(d.supabase, usuario.upper(), d.AMBIENTE,
                                progreso=lambda t, f: print(f"[RESPALDO] {int(f * 100):3d}% {t}"))
        print(f"[RESPALDO] {res['estado']}: {res['tablas']} tablas, {res['filas']} filas, "
              f"{res['bytes'] / 1_048_576:.1f} MB en {res['ruta']}")
        d.cerrar_sesion_pc(None)
        return 0 if res["estado"] == "OK" else 1
    except Exception as ex:
        print(f"[RESPALDO] ERROR: {ex}")
        try:
            d.supabase.rpc("wms_registrar_error", {"p_origen": "PC", "p_modulo": "RESPALDO",
                                                   "p_mensaje": f"Respaldo programado falló: {ex}"[:500]}).execute()
        except Exception:
            pass
        return 1
