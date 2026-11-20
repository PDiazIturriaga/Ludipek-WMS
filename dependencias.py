import flet as ft
from supabase import create_client, Client
from datetime import datetime
import asyncio
import os
import sys
import json
import inspect
import qrcode
from fpdf import FPDF
import pandas as pd
import plotly.graph_objects as go
import hashlib
import hmac
import shutil
import urllib.parse

# Importaciones para el generador de etiquetas B2B (Cencosud)
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.graphics.barcode import code128

# Importaciones forzadas para compilar correctamente la app como .exe con PyInstaller
import reportlab.graphics.barcode.code93
import reportlab.graphics.barcode.code39
import reportlab.graphics.barcode.usps
import reportlab.graphics.barcode.usps4s
import reportlab.graphics.barcode.ecc200datamatrix



# ---------------------------------------------------------------------
# Menús desplegables oscuros: la app usa tema claro pero pinta los controles
# oscuros. Un Dropdown con bgcolor oscuro mostraba sus opciones en letra negra
# sobre fondo negro. Este parche da letra clara a las opciones de esos menús
# (solo a las que no traen su propio contenido) en TODOS los módulos.
# ---------------------------------------------------------------------
_MARCA_OPCION_CLARA = "_ludipek_opcion_clara"


def _es_color_oscuro(color) -> bool:
    s = str(color or "").strip()
    if not s.startswith("#"):
        return False
    h = s[1:]
    if len(h) == 8:          # #AARRGGBB
        h = h[2:]
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return False
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return False
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


def _aclarar_opciones_dropdown(dd) -> None:
    if not _es_color_oscuro(getattr(dd, "bgcolor", None)):
        return
    for op in (getattr(dd, "options", None) or []):
        texto = getattr(op, "text", None) or str(getattr(op, "key", "") or "")
        actual = getattr(op, "content", None)
        if actual is None:
            op.content = ft.Text(texto, size=12.5, color="#E5E7EB", data=_MARCA_OPCION_CLARA)
        elif getattr(actual, "data", None) == _MARCA_OPCION_CLARA and getattr(actual, "value", None) != texto:
            actual.value = texto


def _instalar_parche_dropdown_oscuro() -> None:
    if getattr(ft.Dropdown, "_ludipek_parche_oscuro", False):
        return
    original = getattr(ft.Dropdown, "before_update", None)

    def before_update(self):
        try:
            _aclarar_opciones_dropdown(self)
        except Exception as ex:   # nunca romper la pantalla por el estilo
            print(f"[WARN] Estilo de menú desplegable: {ex}")
        if callable(original):
            return original(self)

    ft.Dropdown.before_update = before_update
    ft.Dropdown._ludipek_parche_oscuro = True


try:
    _instalar_parche_dropdown_oscuro()
except Exception as _ex_parche:
    print(f"[WARN] No se aplicó el estilo de menús oscuros: {_ex_parche}")

def obtener_ruta_recurso(relativo: str) -> str:
    """Obtiene la ruta absoluta del recurso, compatible con desarrollo y con PyInstaller (.exe)."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relativo)


# Ambiente: PRODUCCION (por defecto) o PRUEBAS. El de pruebas lee .env.pruebas, que apunta a
# otro proyecto de Supabase, y la pantalla lo muestra con una franja naranja.
#   Abrir en pruebas:  python main.py --pruebas   (o la variable WMS_AMBIENTE=PRUEBAS)
AMBIENTE = "PRUEBAS" if ("--pruebas" in sys.argv or os.getenv("WMS_AMBIENTE", "").strip().upper() == "PRUEBAS") else "PRODUCCION"

try:
    from dotenv import load_dotenv
    if AMBIENTE == "PRUEBAS":
        _env_pruebas = next((p for p in (os.path.abspath(".env.pruebas"),
                                         os.path.join(os.path.dirname(os.path.abspath(sys.argv[0] or ".")), ".env.pruebas"))
                             if os.path.exists(p)), None)
        if not _env_pruebas:
            raise RuntimeError("Ambiente de PRUEBAS: falta el archivo .env.pruebas junto al programa.")
        load_dotenv(_env_pruebas, override=True)
    else:
        load_dotenv()
except ImportError:
    pass

# =====================================================================
# 1. CONEXIÓN ERP NETSUITE (LOCAL Y RENDER CLOUD)
# =====================================================================
RUTAS_ERP = [
    os.path.abspath("."),
    r"C:\WMS_Clean",
    r"C:\Scripts\Supabase",
]
for ruta in RUTAS_ERP:
    if os.path.exists(ruta) and ruta not in sys.path:
        sys.path.append(ruta)

NETSUITE_CONECTADO = False
ERROR_DETALLE_ERP = ""

try:
    from conexion_erp import consultar_netsuite
    NETSUITE_CONECTADO = True
    print("[INFO] Modulo 'conexion_erp' cargado correctamente.")
except Exception as err_erp:
    NETSUITE_CONECTADO = False
    ERROR_DETALLE_ERP = str(err_erp)
    print(f"[WARN] Detalle al importar 'conexion_erp': {ERROR_DETALLE_ERP}")

# =====================================================================
# 2. IA GOOGLE GEMINI Y SUPABASE (100% VARIABLES DE ENTORNO)
# =====================================================================
try:
    from google import genai
    from google.genai import types
    GEMINI_DISPONIBLE = True
except ImportError:
    GEMINI_DISPONIBLE = False

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY en las variables de entorno (.env o Render).")

_cliente_base: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
_clientes_sesion = {}      # id(page) -> (referencia débil a la pantalla, cliente con la sesión de ese usuario)


def _clientes_vigentes() -> list:
    """Clientes de pantallas que siguen abiertas (descarta las cerradas sin cerrar sesión)."""
    for k, (ref, _c) in list(_clientes_sesion.items()):
        if ref is not None and ref() is None:
            _clientes_sesion.pop(k, None)
    return [c for _r, c in _clientes_sesion.values()]


class _SupabaseSegunUsuario:
    """Con la llave maestra es el cliente de siempre. Con la llave pública (modo SESION) cada
    pantalla abierta (cada usuario conectado a este programa) usa su propio cliente con su sesión;
    así dos personas en el mismo servidor nunca comparten la sesión."""

    def _actual(self):
        if MODO_CONEXION_PC == "SESION" and _clientes_sesion:
            try:
                pg = ft.context.page
                c = getattr(pg, "_wms_cliente", None)
                if c is not None:
                    return c
            except Exception:
                pass
            vigentes = _clientes_vigentes()
            if len(vigentes) == 1:                  # un solo usuario: también en hilos de fondo
                return vigentes[0]
        return _cliente_base

    def __getattr__(self, nombre):
        return getattr(self._actual(), nombre)


supabase: Client = _SupabaseSegunUsuario()


# =====================================================================
# 2b. MODO DE CONEXIÓN DEL PC (script 36)
#   LLAVE_MAESTRA: SUPABASE_KEY es la llave secreta (service_role). Funciona como siempre.
#   SESION:        SUPABASE_KEY es la llave pública. Cada usuario abre una sesión verificada
#                  y la base aplica los permisos. Es lo recomendado.
# =====================================================================
def _rol_de_llave(llave: str) -> str:
    llave = str(llave or "").strip()
    if llave.startswith("sb_secret_"):
        return "service_role"
    if llave.startswith("sb_publishable_"):
        return "anon"
    try:
        import base64 as _b64
        import json as _json
        carga = llave.split(".")[1]
        carga += "=" * (-len(carga) % 4)
        return str(_json.loads(_b64.urlsafe_b64decode(carga)).get("role") or "")
    except Exception:
        return ""


MODO_CONEXION_PC = "SESION" if _rol_de_llave(SUPABASE_KEY) == "anon" else "LLAVE_MAESTRA"


def _nombre_equipo() -> str:
    try:
        import socket as _socket
        return _socket.gethostname()[:60]
    except Exception:
        return "PC"


def iniciar_sesion_pc(usuario: str, password: str, page=None):
    """Modo SESION: abre la sesión verificada del PC con un cliente propio para esta pantalla.
    Devuelve el usuario (dict), None si la contraseña es incorrecta, o {'error': ...}.
    Lanza excepción con el motivo si no se pudo."""
    cliente = create_client(SUPABASE_URL, SUPABASE_KEY)
    if not hasattr(cliente.auth, "sign_in_anonymously"):
        raise RuntimeError("La librería supabase de este PC es antigua. Actualícela: pip install -U supabase")
    cliente.auth.sign_in_anonymously()
    res = cliente.rpc("wms_iniciar_sesion_pc", {
        "p_usuario": usuario, "p_password": password,
        "p_equipo": f"PC {_nombre_equipo()}" + (" · PRUEBAS" if AMBIENTE == "PRUEBAS" else ""),
    }).execute()
    datos = res.data if isinstance(res.data, dict) else None
    if datos and not datos.get("error"):
        import weakref as _weakref
        clave = id(page) if page is not None else 0
        try:
            ref = _weakref.ref(page) if page is not None else None
        except TypeError:
            ref = None
        _clientes_sesion[clave] = (ref, cliente)
        if page is not None:
            page._wms_cliente = cliente
    else:
        try:
            cliente.auth.sign_out()
        except Exception:
            pass
    return datos


def cerrar_sesion_pc(page=None) -> None:
    if MODO_CONEXION_PC != "SESION":
        return
    clave = id(page) if page is not None else 0
    par = _clientes_sesion.pop(clave, None)
    cliente = (par[1] if par else None) or (getattr(page, "_wms_cliente", None) if page is not None else None)
    if page is not None:
        page._wms_cliente = None
    if cliente is None:
        return
    try:
        cliente.rpc("wms_cerrar_sesion", {}).execute()
    except Exception:
        pass
    try:
        cliente.auth.sign_out()
    except Exception:
        pass


def registrar_conexion_pc(usuario: str) -> None:
    """Deja constancia de cómo se conecta este PC (Salud del sistema avisa si usa la llave maestra)."""
    def _enviar():
        try:
            supabase.rpc("wms_registrar_conexion_pc", {
                "p_usuario": usuario, "p_equipo": _nombre_equipo(), "p_modo": MODO_CONEXION_PC,
                "p_ambiente": AMBIENTE, "p_version": CONTEXTO_ERRORES_PC.get("version"),
            }).execute()
        except Exception:
            pass
    _threading.Thread(target=_enviar, daemon=True).start()


# ---------------------------------------------------------------------
# Registro central de errores del PC (script 26): todo error que el programa
# escriba en el log con nivel ERROR (incluye fallas dentro de botones y pantallas)
# queda en wms_log_errores para que se vea en "Requiere atención".
# ---------------------------------------------------------------------
import logging as _logging
import threading as _threading

CONTEXTO_ERRORES_PC = {"usuario": "", "bodega": "", "version": "PC", "modulo": ""}
_estado_registro_pc = {"ultimo": "", "en": 0.0}
_guardia_registro = _threading.local()


def fijar_contexto_errores_pc(usuario=None, bodega=None) -> None:
    if usuario is not None:
        CONTEXTO_ERRORES_PC["usuario"] = str(usuario or "")
    if bodega is not None:
        CONTEXTO_ERRORES_PC["bodega"] = str(bodega or "")


def registrar_error_pc(modulo: str, mensaje: str, detalle: str = "") -> None:
    """Envía el error a Supabase en segundo plano. Nunca lanza excepción."""
    import time as _time
    try:
        msg = str(mensaje or "").strip()
        if not msg or msg.startswith("WMS:"):
            return
        ahora = _time.time()
        if msg == _estado_registro_pc["ultimo"] and ahora - _estado_registro_pc["en"] < 60:
            return
        _estado_registro_pc.update(ultimo=msg, en=ahora)

        def _enviar():
            if getattr(_guardia_registro, "activo", False):
                return
            _guardia_registro.activo = True
            try:
                supabase.rpc("wms_registrar_error", {
                    "p_origen": "PC", "p_modulo": str(modulo or "")[:60], "p_mensaje": msg[:500],
                    "p_detalle": str(detalle or "")[:3000], "p_version": CONTEXTO_ERRORES_PC.get("version"),
                    "p_usuario": CONTEXTO_ERRORES_PC.get("usuario"), "p_bodega": CONTEXTO_ERRORES_PC.get("bodega") or None,
                }).execute()
            except Exception:
                pass
            finally:
                _guardia_registro.activo = False

        _threading.Thread(target=_enviar, daemon=True).start()
    except Exception:
        pass


class _ManejadorErroresPc(_logging.Handler):
    def emit(self, record):
        try:
            if record.levelno < _logging.ERROR or getattr(_guardia_registro, "activo", False):
                return
            detalle = ""
            if record.exc_info:
                import traceback as _tb
                detalle = "".join(_tb.format_exception(*record.exc_info))
            msg = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                msg = f"{type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
            registrar_error_pc(record.name, msg, detalle)
        except Exception:
            pass


try:
    if not any(isinstance(h, _ManejadorErroresPc) for h in _logging.getLogger().handlers):
        _logging.getLogger().addHandler(_ManejadorErroresPc(level=_logging.ERROR))
except Exception:
    pass
ai_client = genai.Client(api_key=GEMINI_API_KEY) if (GEMINI_DISPONIBLE and GEMINI_API_KEY) else None


# =====================================================================
# 3. ADAPTADORES INTELIGENTES DE ESQUEMA Y MULTI-BODEGA
# =====================================================================
def obtener_bodega_activa(page) -> str:
    """Devuelve siempre la bodega activa de la sesión ('Bodega Santiago' o 'Bodega Concepcion')."""
    if page is not None:
        bod = str(getattr(page, "bodega_actual", "") or "").strip()
        if bod in ("Bodega Santiago", "Bodega Concepcion"):
            return bod
    return "Bodega Santiago"


def coincide_bodega(fila: dict, bodega_objetivo: str) -> bool:
    """Valida si un registro pertenece a la bodega activa (asignando registros antiguos sin bodega a 'Bodega Santiago')."""
    if not isinstance(fila, dict):
        return False
    bod_obj = str(bodega_objetivo or "Bodega Santiago").strip()
    bod_fila = str(fila.get("bodega") or "").strip()
    if not bod_fila or bod_fila.upper() in ("NONE", "NULL"):
        return bod_obj.upper() == "BODEGA SANTIAGO"
    return bod_fila.upper() == bod_obj.upper()


def leer_tabla_paginada(construir_consulta, paso: int = 1000, max_filas: int = 100000) -> list:
    """Lee TODAS las filas de una consulta Supabase.

    PostgREST corta cada respuesta en 1.000 filas (max_rows), aunque se pida
    .limit(5000). construir_consulta() debe devolver una consulta nueva
    (ej: lambda: supabase.table("maestra_sku").select("*")).
    """
    filas = []
    desde = 0
    while desde < max_filas:
        res = construir_consulta().range(desde, desde + paso - 1).execute()
        lote = res.data or []
        if not lote:
            break
        filas.extend(lote)
        desde += len(lote)
    return filas


def leer_por_lista(tabla: str, columna: str, valores, columnas: str = "*", tamano_bloque: int = 150) -> list:
    """Lee filas cuya `columna` está en `valores`, en bloques (evita URLs gigantes y el tope de 1.000 filas)."""
    unicos = [v for v in dict.fromkeys(valores) if v is not None and str(v).strip() != ""]
    filas = []
    for i in range(0, len(unicos), tamano_bloque):
        bloque = unicos[i:i + tamano_bloque]
        filas.extend(
            leer_tabla_paginada(lambda b=bloque: supabase.table(tabla).select(columnas).in_(columna, b))
        )
    return filas


def lista_permisos(valor) -> list:
    """Permisos de wms_usuarios (columnas text[]): acepta lista, texto 'A,B' o '{A,B}'."""
    if valor is None:
        return []
    if isinstance(valor, (list, tuple, set)):
        items = valor
    else:
        items = str(valor).strip().strip("{}[]").replace(";", ",").split(",")
    return [str(x).strip().strip("'\"").upper() for x in items if str(x).strip().strip("'\"")]


def obtener_val(diccionario: dict, posibles_claves: list, por_defecto=""):
    if not isinstance(diccionario, dict):
        return por_defecto
    for k in posibles_claves:
        if k in diccionario and diccionario[k] is not None:
            return diccionario[k]
    return por_defecto


def formatear_nombre_po(codigo_raw: str) -> str:
    txt = str(codigo_raw or "").strip()
    for prefijo in ("ASN-", "PO-", "OC-", "ASN ", "PO ", "OC "):
        if txt.upper().startswith(prefijo):
            txt = txt[len(prefijo):].strip()
    # Reemplazar barras o caracteres prohibidos en nombres de archivo de Windows
    for char_invalido in ("/", "\\", ":", "*", "?", '"', "<", ">", "|"):
        txt = txt.replace(char_invalido, "-")
    return txt or "LIBRE"


def obtener_nombre_po_cabecera(cabecera: dict) -> str:
    """Obtiene el código real de la PO ignorando placeholders como 'S/OC' o 'S/N'."""
    if not isinstance(cabecera, dict):
        return "LIBRE"
    num_oc = str(cabecera.get("numero_oc") or "").strip()
    cod_asn = str(cabecera.get("codigo_asn") or "").strip()

    # Si numero_oc tiene un valor real (distinto de S/OC o S/N), usarlo; si no, usar codigo_asn
    if num_oc and num_oc.upper() not in ("S/OC", "S/N", "NONE", "NULL", "-"):
        return formatear_nombre_po(num_oc)
    if cod_asn and cod_asn.upper() not in ("S/OC", "S/N", "NONE", "NULL", "-"):
        return formatear_nombre_po(cod_asn)
    return "LIBRE"


def extraer_estado_qa(lote_str: str) -> tuple[str, str]:
    raw = str(lote_str or "S/L").strip()
    if "|QA:" in raw:
        partes = raw.split("|QA:")
        return partes[0].strip(), partes[1].strip()
    return raw, "APROBADO"


def formatear_lote_con_qa(lote_limpio: str, estado_qa: str) -> str:
    lote_base = str(lote_limpio or "S/L").split("|QA:")[0].strip().upper()
    est = str(estado_qa or "APROBADO").strip().upper()
    if est == "APROBADO":
        return lote_base
    return f"{lote_base}|QA:{est}"


# =====================================================================
# 4. MOTOR DE REPORTES PDF (INDIVIDUAL Y MASIVO DE LPNs) Y EXCEL
# =====================================================================
def obtener_ahora_chile() -> datetime:
    """Devuelve siempre la fecha y hora exacta de Chile (America/Santiago), incluso en servidores UTC como Render."""
    from datetime import timezone, timedelta
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Santiago"))
    except Exception:
        return datetime.now(timezone(timedelta(hours=-3)))


def formatear_fecha_hora_chile(valor_raw=None) -> str:
    """Convierte un timestamp ISO de Supabase a hora local de Chile o usa la hora actual de Chile."""
    from datetime import timezone, timedelta
    try:
        from zoneinfo import ZoneInfo
        tz_cl = ZoneInfo("America/Santiago")
    except Exception:
        tz_cl = timezone(timedelta(hours=-3))

    if valor_raw and str(valor_raw).strip() not in ("None", "null", ""):
        txt = str(valor_raw).strip()
        try:
            dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(tz_cl).strftime("%d-%m-%Y %H:%M")
        except Exception:
            pass
    return obtener_ahora_chile().strftime("%d-%m-%Y %H:%M")


def dibujar_pagina_lpn_15x10(pdf: FPDF, lpn: str, lineas_pallet: list):
    """Dibuja una etiqueta 15x10 cm con hora de Chile y recuadros de Lote y Fecha de Vencimiento (sin QA)."""
    import qrcode
    os.makedirs("temp_qrs", exist_ok=True)
    qr_path = f"temp_qrs/{_nombre_archivo_seguro(lpn)}.png"
    qr_img = qrcode.make(lpn)
    qr_img.save(qr_path)

    primera = lineas_pallet[0] if lineas_pallet else {}
    raw_fecha_rec = (
        primera.get("fecha_recepcion")
        or primera.get("created_at")
        or primera.get("timestamp")
    )
    fecha_rec_cl = formatear_fecha_hora_chile(raw_fecha_rec)

    pdf.add_page()
    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)

    # Marco exterior grueso
    pdf.set_line_width(0.6)
    pdf.rect(1.5, 1.5, 147, 97)

    # --- ENCABEZADO: N° LPN GIGANTE ARRIBA + QR EN ESQUINA SUPERIOR DERECHA ---
    lpn_str = str(lpn or "S/LPN").strip().upper()
    tam_fuente_lpn = 46 if len(lpn_str) <= 12 else (38 if len(lpn_str) <= 15 else 30)
    pdf.set_font("Helvetica", "B", tam_fuente_lpn)
    pdf.set_xy(4, 3.5)
    pdf.cell(118, 17, txt=lpn_str, align="L")

    # Fecha de recepción en hora oficial de Chile
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(4, 21)
    pdf.cell(116, 5, txt=f"FECHA RECP: {fecha_rec_cl}", align="L")

    # QR en la esquina superior derecha (22x22 mm)
    pdf.image(qr_path, x=124, y=3.5, w=22)

    # Línea divisoria superior
    pdf.set_line_width(0.5)
    pdf.line(1.5, 27.5, 148.5, 27.5)

    if len(lineas_pallet) == 1:
        # CASO 1: SKU ÚNICO Y LOTE ÚNICO (CON LOTE Y VENCIMIENTO VISIBLES)
        item = lineas_pallet[0]
        sku_str = str(item.get("sku", "")).strip().upper()
        cajas_val = item.get("cajas", 0)
        mult_val = item.get("multiplo_aplicado", 1)
        unid_totales = item.get("unidades_totales", 0)
        lote_val, _ = extraer_estado_qa(item.get("lote", "S/L"))
        venc_val = str(item.get("fecha_vencimiento_cl") or "S/F").strip()

        # 1. SKU GIGANTE
        tam_sku = 38 if len(sku_str) <= 12 else 30
        pdf.set_font("Helvetica", "B", tam_sku)
        pdf.set_xy(3, 29)
        pdf.cell(144, 13.5, txt=f"SKU: {sku_str}", align="C")

        # 2. BLOQUES GRANDES: CAJAS Y UNIDADES
        pdf.set_line_width(0.4)
        # Cajas
        pdf.rect(4, 44, 69, 21)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_xy(4, 45)
        pdf.cell(69, 4.5, txt="CAJAS", align="C")
        pdf.set_font("Helvetica", "B", 36)
        pdf.set_xy(4, 50)
        pdf.cell(69, 13.5, txt=f"{cajas_val}", align="C")

        # Unidades
        pdf.rect(77, 44, 69, 21)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_xy(77, 45)
        pdf.cell(69, 4.5, txt=f"TOTAL UNID (x{mult_val})", align="C")
        pdf.set_font("Helvetica", "B", 36)
        pdf.set_xy(77, 50)
        pdf.cell(69, 13.5, txt=f"{unid_totales}", align="C")

        # 3. RECUADRO LOTE
        tam_lote = 28 if len(str(lote_val)) <= 14 else 22
        pdf.set_font("Helvetica", "B", tam_lote)
        pdf.set_xy(4, 67)
        pdf.cell(142, 13.5, txt=f"LOTE: {lote_val}", border=1, align="C")

        # 4. RECUADRO FECHA DE VENCIMIENTO (SIN QA)
        pdf.set_font("Helvetica", "B", 24)
        pdf.set_xy(4, 82.5)
        pdf.cell(142, 13, txt=f"VENC: {venc_val}", border=1, align="C")

    else:
        # CASO 2: PALLET MIXTO (MULTI-LOTE O MULTI-SKU)
        skus_distintos = list(set([str(x.get("sku", "")).upper() for x in lineas_pallet]))
        total_cj = sum(int(x.get("cajas") or 0) for x in lineas_pallet)
        total_un = sum(int(x.get("unidades_totales") or 0) for x in lineas_pallet)

        if len(skus_distintos) == 1:
            sku_unico = skus_distintos[0]
            pdf.set_font("Helvetica", "B", 36)
            pdf.set_xy(3, 29.5)
            pdf.cell(144, 13, txt=f"SKU: {sku_unico}", align="C")

            pdf.set_font("Helvetica", "B", 15)
            pdf.set_xy(3, 44)
            pdf.cell(144, 6, txt=f"PALLET MULTI-LOTE | TOTAL: {total_cj} CJ / {total_un} UN", align="C")

            pdf.set_font("Helvetica", "B", 14)
            pdf.set_xy(4, 52)
            pdf.cell(52, 10, "LOTE", border=1, align="C")
            pdf.cell(36, 10, "VENC.", border=1, align="C")
            pdf.cell(24, 10, "CAJAS", border=1, align="C")
            pdf.cell(30, 10, "UNIDADES", border=1, align="C")

            y_offset = 62
            pdf.set_font("Helvetica", "B", 14)
            for item in lineas_pallet[:3]:
                lote_clean, _ = extraer_estado_qa(item.get("lote", "S/L"))
                venc = str(item.get("fecha_vencimiento_cl") or "S/F")
                pdf.set_xy(4, y_offset)
                pdf.cell(52, 10.5, lote_clean[:14], border=1, align="C")
                pdf.cell(36, 10.5, venc[:10], border=1, align="C")
                pdf.cell(24, 10.5, str(item.get("cajas", 0)), border=1, align="C")
                pdf.cell(30, 10.5, str(item.get("unidades_totales", 0)), border=1, align="C")
                y_offset += 10.5
        else:
            pdf.set_font("Helvetica", "B", 20)
            pdf.set_xy(4, 30)
            pdf.cell(142, 8, txt="PALLET MIXTO MULTI-SKU", align="C")

            pdf.set_font("Helvetica", "B", 14)
            pdf.set_xy(4, 38)
            pdf.cell(142, 6, txt=f"TOTALES PALLET: {total_cj} CAJAS / {total_un} UNIDADES", align="C")

            pdf.set_font("Helvetica", "B", 13)
            pdf.set_xy(4, 47)
            pdf.cell(46, 10, "SKU", border=1, align="C")
            pdf.cell(38, 10, "LOTE", border=1, align="C")
            pdf.cell(16, 10, "CJ", border=1, align="C")
            pdf.cell(18, 10, "UNID", border=1, align="C")
            pdf.cell(24, 10, "VENC.", border=1, align="C")

            y_offset = 57
            pdf.set_font("Helvetica", "B", 13)
            for item in lineas_pallet[:4]:
                lote_clean, _ = extraer_estado_qa(item.get("lote", "S/L"))
                venc = str(item.get("fecha_vencimiento_cl") or "S/F")
                pdf.set_xy(4, y_offset)
                pdf.cell(46, 10, str(item.get("sku", ""))[:16], border=1, align="L")
                pdf.cell(38, 10, lote_clean[:14], border=1, align="C")
                pdf.cell(16, 10, str(item.get("cajas", 0)), border=1, align="C")
                pdf.cell(18, 10, str(item.get("unidades_totales", 0)), border=1, align="C")
                pdf.cell(24, 10, venc[:10], border=1, align="C")
                y_offset += 10


def generar_pdf_recepcion_15x10(lpn: str, lineas_pallet: list):
    os.makedirs("reportes_recepcion", exist_ok=True)
    pdf = FPDF(orientation="L", unit="mm", format=(100, 150))
    pdf.set_auto_page_break(auto=False, margin=0)
    dibujar_pagina_lpn_15x10(pdf, lpn, lineas_pallet)

    nombre_archivo = os.path.join("reportes_recepcion", f"Etiqueta_{lpn}.pdf")
    pdf.output(nombre_archivo)
    if os.name == "nt":
        try:
            os.startfile(nombre_archivo)
        except Exception:
            pass
    return nombre_archivo


def generar_pdf_masivo_lpns_po(codigo_po: str, registros_recepcion: list) -> str:
    """Genera un único PDF multipágina con TODOS los LPNs de la PO listos para imprimir."""
    os.makedirs("reportes_recepcion", exist_ok=True)
    pdf = FPDF(orientation="L", unit="mm", format=(100, 150))
    pdf.set_auto_page_break(auto=False, margin=0)

    agrupado_lpn = {}
    for r in registros_recepcion:
        cod = str(r.get("lpn", "")).strip()
        if cod:
            agrupado_lpn.setdefault(cod, []).append(r)

    for cod_lpn in sorted(agrupado_lpn.keys()):
        dibujar_pagina_lpn_15x10(pdf, cod_lpn, agrupado_lpn[cod_lpn])

    po_limpia = formatear_nombre_po(codigo_po).replace("/", "-")
    nombre_archivo = os.path.join(
        "reportes_recepcion",
        f"Etiquetas_Masivas_{po_limpia}_{datetime.now().strftime('%H%M%S')}.pdf",
    )
    pdf.output(nombre_archivo)
    if os.name == "nt":
        try:
            os.startfile(nombre_archivo)
        except Exception:
            pass
    return nombre_archivo

def generar_pdf_etiqueta_packing_bultos_15x10(
    lpn: str,
    numero_ov: str,
    cliente: str,
    comuna: str,
    tipo_empaque: str = "BULTO",
    total_bultos: int = 1,
) -> str:
    """Genera el PDF 15x10 cm de Packing con 1 etiqueta y LPN correlativo por cada Bulto/Pallet (1 de N, 2 de N...)."""
    import qrcode

    os.makedirs("temp_qrs", exist_ok=True)
    os.makedirs("reportes_recepcion", exist_ok=True)

    lpn_limpio = str(lpn or "S/LPN").strip().upper().split(" (")[0].strip()
    ov_limpia = str(numero_ov or "S/OV").strip().upper()
    cli_limpio = _texto_pdf_seguro(str(cliente or "SIN CLIENTE").strip().upper())
    comuna_limpia = _texto_pdf_seguro(str(comuna or "POR CONFIRMAR").strip().upper())
    tipo_limpio = _texto_pdf_seguro(str(tipo_empaque or "BULTO").strip().upper())
    cant_bultos = max(1, min(int(total_bultos or 1), 200))
    fecha_cl = formatear_fecha_hora_chile()

    pdf = FPDF(orientation="L", unit="mm", format=(100, 150))
    pdf.set_auto_page_break(auto=False, margin=0)

    for num_b in range(1, cant_bultos + 1):
        lpn_bulto = f"{lpn_limpio}-B{num_b}" if cant_bultos > 1 else lpn_limpio
        qr_data = f"{lpn_bulto}|OV:{ov_limpia}|{tipo_limpio}:{num_b}/{cant_bultos}"
        qr_path = os.path.join("temp_qrs", f"pk_{_nombre_archivo_seguro(lpn_bulto)}.png")
        qrcode.make(qr_data).save(qr_path)

        pdf.add_page()
        pdf.set_text_color(0, 0, 0)
        pdf.set_draw_color(0, 0, 0)

        pdf.set_line_width(0.7)
        pdf.rect(2, 2, 146, 96)

        # 1. CABECERA: LPN POR BULTO + FECHA EMPAQUE + QR
        tam_lpn = 26 if len(lpn_bulto) <= 18 else 20
        pdf.set_font("Helvetica", "B", tam_lpn)
        pdf.set_xy(5, 4)
        pdf.cell(115, 13, txt=_texto_pdf_seguro(lpn_bulto), align="L")

        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_xy(5, 18)
        pdf.cell(115, 5, txt=f"FECHA PACKING: {fecha_cl}", align="L")

        pdf.image(qr_path, x=124, y=3.5, w=21, h=21)
        pdf.set_line_width(0.5)
        pdf.line(2, 26, 148, 26)

        # 2. OV / OT EN GRANDE
        pref_doc = "" if (ov_limpia.startswith("OV") or ov_limpia.startswith("OT")) else "OV "
        pdf.set_font("Helvetica", "B", 28)
        pdf.set_xy(4, 28)
        pdf.cell(142, 13, txt=_texto_pdf_seguro(f"{pref_doc}{ov_limpia}"[:22]), border=1, align="C")

        # 3. CLIENTE
        pdf.rect(4, 43, 142, 16)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_xy(6, 44)
        pdf.cell(138, 4.5, txt="CLIENTE / DESTINO:", align="L")
        tam_cli = 15 if len(cli_limpio) <= 28 else 11.5
        pdf.set_font("Helvetica", "B", tam_cli)
        pdf.set_xy(6, 49)
        pdf.cell(138, 8, txt=cli_limpio[:42], align="L")

        # 4. COMUNA DE DESPACHO
        pdf.rect(4, 61, 142, 15)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_xy(6, 62)
        pdf.cell(138, 4.5, txt="COMUNA DE DESPACHO:", align="L")
        pdf.set_font("Helvetica", "B", 17)
        pdf.set_xy(6, 66.5)
        pdf.cell(138, 8, txt=comuna_limpia[:32], align="L")

        # 5. RECUADRO INFERIOR GIGANTE: BULTO / PALLET X DE Y
        pdf.set_fill_color(15, 23, 42)
        pdf.rect(4, 78, 142, 17, style="F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 24)
        pdf.set_xy(4, 80.5)
        pdf.cell(142, 12, txt=f"{tipo_limpio}: {num_b} DE {cant_bultos}", align="C")
        pdf.set_text_color(0, 0, 0)

    nombre_out = os.path.join(
        "reportes_recepcion",
        f"Etiqueta_Packing_{_nombre_archivo_seguro(ov_limpia)}_{_nombre_archivo_seguro(lpn_limpio)}.pdf",
    )
    pdf.output(nombre_out)
    return nombre_out


def obtener_fecha_cierre_o_recepcion(cabecera_po: dict, recepciones_lpn: list) -> str:
    """Obtiene la fecha fija de cierre de la PO o la del último LPN recepcionado."""
    if isinstance(cabecera_po, dict):
        for col_f in ("fecha_cierre", "closed_at", "updated_at"):
            val_f = cabecera_po.get(col_f)
            if val_f and str(val_f).strip() not in ("None", ""):
                txt_f = str(val_f).strip()
                try:
                    dt_iso = datetime.fromisoformat(txt_f.replace("Z", "+00:00")).astimezone()
                    return dt_iso.strftime("%d-%m-%Y %H:%M:%S")
                except Exception:
                    return txt_f[:19]

    if recepciones_lpn:
        ultimo_lpn = recepciones_lpn[0]
        for col_r in ("created_at", "fecha_recepcion", "fecha_hora", "fecha_ingreso", "timestamp"):
            val_r = ultimo_lpn.get(col_r)
            if val_r and str(val_r).strip() not in ("None", ""):
                txt_r = str(val_r).strip()
                try:
                    dt_lpn = datetime.fromisoformat(txt_r.replace("Z", "+00:00")).astimezone()
                    return dt_lpn.strftime("%d-%m-%Y %H:%M:%S")
                except Exception:
                    return txt_r[:19]

    return datetime.now().strftime("%d-%m-%Y %H:%M:%S")


def _texto_pdf_seguro(texto) -> str:
    """Convierte cualquier texto a latin-1 seguro para que FPDF nunca falle por símbolos o tildes."""
    s = str(texto or "").replace("•", "-").replace("—", "-").replace("–", "-")
    return s.encode("latin-1", "replace").decode("latin-1")


def _nombre_archivo_seguro(texto: str) -> str:
    """Elimina barras, pipes (|) y espacios para nombres de archivo y URLs web seguras."""
    limpio = "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in str(texto or ""))
    while "__" in limpio:
        limpio = limpio.replace("__", "_")
    return limpio.strip("_")[:45] or "DOC"


def generar_acta_recepcion_pdf(cabecera_po: dict, filas_conciliacion: list, recepciones_lpn: list) -> str:
    import os
    from fpdf import FPDF
    from datetime import datetime

    os.makedirs("reportes_recepcion", exist_ok=True)

    codigo_po = str(cabecera_po.get("codigo_asn") or "S/PO").strip()
    proveedor = str(cabecera_po.get("proveedor") or "RECEPCION DIRECTA").strip()
    oc_raw = str(cabecera_po.get("numero_oc") or "").strip()
    oc_num = codigo_po if oc_raw.upper() in ("", "S/OC", "S/N", "NONE") else oc_raw
    estado_po = str(cabecera_po.get("estado") or "EN_RECEPCION").strip()
    contenedor_guia = str(cabecera_po.get("contenedor_referencia") or "N/A").strip()

    try:
        fecha_cierre_str = obtener_fecha_cierre_o_recepcion(cabecera_po, recepciones_lpn)
    except Exception:
        fecha_cierre_str = datetime.now().strftime("%d-%m-%Y %H:%M")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # --- ENCABEZADO CON LOGO.PNG Y COLOR CORPORATIVO ---
    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, 210, 26, style="F")

    posibles_logos = [
        obtener_ruta_recurso("logo.png"),
        obtener_ruta_recurso(os.path.join("assets", "logo.png")),
        "logo.png",
        os.path.join("assets", "logo.png"),
    ]
    ruta_logo = next((p for p in posibles_logos if os.path.exists(p)), None)

    x_texto_header = 10
    if ruta_logo:
        try:
            pdf.image(ruta_logo, x=10, y=3, h=20)
            x_texto_header = 38
        except Exception:
            pass

    fecha_llegada = "EN PROCESO / NO REGISTRADA"
    if recepciones_lpn:
        primer_lpn = sorted(recepciones_lpn, key=lambda x: x.get("id") or 0)[0]
        val_r = primer_lpn.get("created_at") or primer_lpn.get("fecha_recepcion") or primer_lpn.get("timestamp")
        if val_r and str(val_r).strip() not in ("None", ""):
            try:
                dt_llegada = datetime.fromisoformat(str(val_r).replace("Z", "+00:00"))
                fecha_llegada = dt_llegada.strftime("%d-%m-%Y %H:%M")
            except Exception:
                fecha_llegada = str(val_r)[:16]

    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(x_texto_header, 5)
    pdf.cell(200 - x_texto_header, 6, txt=_texto_pdf_seguro(f"LUDIPEK WMS - ACTA DE RECEPCION (OC: {oc_num})"), align="L")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(x_texto_header, 13)
    pdf.cell(200 - x_texto_header, 5, txt=_texto_pdf_seguro(f"Llegada a Centro de Distribucion: {fecha_llegada}"), align="L")
    pdf.set_xy(x_texto_header, 18)
    pdf.cell(200 - x_texto_header, 5, txt=_texto_pdf_seguro(f"Proceso y Emision en WMS: {fecha_cierre_str}"), align="L")
    pdf.set_text_color(0, 0, 0)

    # --- DATOS DE CABECERA PO ---
    pdf.set_xy(10, 32)
    pdf.set_fill_color(241, 245, 249)
    pdf.rect(10, 32, 190, 22, style="F")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(14, 35)
    pdf.cell(90, 6, txt=_texto_pdf_seguro(f"ORDEN DE COMPRA ERP: {oc_num}"[:42]))
    pdf.cell(90, 6, txt=_texto_pdf_seguro(f"REFERENCIA / NOTA PO: {codigo_po}"[:42]))
    pdf.set_xy(14, 43)
    pdf.cell(90, 6, txt=_texto_pdf_seguro(f"PROVEEDOR: {proveedor[:34]}"))

    str_cont = f" | CONTENEDOR: {contenedor_guia}" if contenedor_guia not in ("N/A", "", "None") else ""
    pdf.cell(90, 6, txt=_texto_pdf_seguro(f"ESTADO: {estado_po}{str_cont}"[:45]))

    # --- 1. TABLA DE CONCILIACION VERTICAL POR SKU Y LOTE ---
    pdf.set_xy(10, 60)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(190, 7, txt="1. TABLA DE CONCILIACION POR LOTE Y SKU (OC VS RECEPCION FISICA)", ln=True)

    lotes_agrupados = {}
    skus_con_recepcion = set()

    for r in recepciones_lpn:
        s_r = str(r.get("sku", "")).strip().upper()
        if not s_r:
            continue
        try:
            lote_limpio, _ = extraer_estado_qa(r.get("lote", "S/L"))
        except Exception:
            lote_limpio = str(r.get("lote", "S/L")).split(" ")[0]

        venc_r = str(r.get("fecha_vencimiento_cl") or "S/F").strip()
        unid_r = int(r.get("unidades_totales", 0) or 0)

        skus_con_recepcion.add(s_r)
        clave = (s_r, lote_limpio)
        if clave not in lotes_agrupados:
            lotes_agrupados[clave] = {"unidades": 0, "vencimiento": venc_r}
        lotes_agrupados[clave]["unidades"] += unid_r
        if lotes_agrupados[clave]["vencimiento"] == "S/F" and venc_r != "S/F":
            lotes_agrupados[clave]["vencimiento"] = venc_r

    # Totales por SKU: OC (suma de TODAS las líneas de la OC) y recibido físico (todos los lotes)
    oc_por_sku = {}
    desc_por_sku = {}
    for f in filas_conciliacion:
        s_f = str(f.get("sku", "")).strip().upper()
        if not s_f:
            continue
        oc_por_sku[s_f] = oc_por_sku.get(s_f, 0) + int(f.get("unidades_esperadas", 0) or 0)
        if s_f not in desc_por_sku and str(f.get("descripcion", "") or "").strip():
            desc_por_sku[s_f] = str(f.get("descripcion", ""))
    recibido_por_sku = {}
    for (sku_k, _lote_k), info_lote in lotes_agrupados.items():
        recibido_por_sku[sku_k] = recibido_por_sku.get(sku_k, 0) + info_lote["unidades"]

    filas_verticales_pdf = []
    sku_ya_mostrado = set()
    for (sku_k, lote_k), info_lote in sorted(lotes_agrupados.items(), key=lambda x: (x[0][0], x[0][1])):
        primera_fila_sku = sku_k not in sku_ya_mostrado
        sku_ya_mostrado.add(sku_k)
        unid_po = oc_por_sku.get(sku_k, 0)
        filas_verticales_pdf.append({
            "sku": sku_k,
            "descripcion": desc_por_sku.get(sku_k, "Ingreso Directo"),
            "lote": lote_k,
            "vencimiento": info_lote["vencimiento"],
            "cantidad_lote": info_lote["unidades"],
            "unidades_po": unid_po,
            # OC y diferencia se informan una sola vez por SKU (en su primer lote)
            "txt_oc": str(unid_po) if primera_fila_sku else "",
            "txt_dif": (f"{recibido_por_sku.get(sku_k, 0) - unid_po:+d}" if primera_fila_sku else ""),
        })

    for f in filas_conciliacion:
        s_key = str(f.get("sku", "")).strip().upper()
        if s_key and s_key not in skus_con_recepcion:
            filas_verticales_pdf.append({
                "sku": s_key,
                "descripcion": str(f.get("descripcion", "")),
                "lote": "SIN INGRESO",
                "vencimiento": "-",
                "cantidad_lote": 0,
                "unidades_po": oc_por_sku.get(s_key, 0),
                "txt_oc": str(oc_por_sku.get(s_key, 0)),
                "txt_dif": f"{-oc_por_sku.get(s_key, 0):+d}",
            })
            skus_con_recepcion.add(s_key)  # evita repetir el SKU si la OC trae varias líneas

    pdf.set_fill_color(226, 232, 240)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(24, 7, "SKU", border=1, fill=True)
    pdf.cell(56, 7, "DESCRIPCION", border=1, fill=True)
    pdf.cell(30, 7, "LOTE", border=1, align="C", fill=True)
    pdf.cell(22, 7, "VENCIMIENTO", border=1, align="C", fill=True)
    pdf.cell(20, 7, "CANT. LOTE", border=1, align="C", fill=True)
    pdf.cell(19, 7, "UNID. OC", border=1, align="C", fill=True)
    pdf.cell(19, 7, "DIF. SKU", border=1, align="C", fill=True, ln=True)

    pdf.set_font("Helvetica", "", 8)
    total_general_unidades = 0
    for fv in filas_verticales_pdf:
        cant_l = fv["cantidad_lote"]
        total_general_unidades += cant_l
        pdf.cell(24, 6, _texto_pdf_seguro(fv["sku"])[:13], border=1)
        pdf.cell(56, 6, _texto_pdf_seguro(fv["descripcion"])[:31], border=1)
        pdf.cell(30, 6, _texto_pdf_seguro(fv["lote"])[:15], border=1, align="C")
        pdf.cell(22, 6, _texto_pdf_seguro(fv["vencimiento"])[:10], border=1, align="C")
        pdf.cell(20, 6, str(cant_l), border=1, align="C")
        pdf.cell(19, 6, fv.get("txt_oc", ""), border=1, align="C")
        txt_dif = fv.get("txt_dif", "")
        if txt_dif and txt_dif not in ("+0", "0"):
            pdf.set_text_color(185, 28, 28)
        pdf.cell(19, 6, txt_dif, border=1, align="C", ln=True)
        pdf.set_text_color(0, 0, 0)

    total_oc_general = sum(oc_por_sku.values())
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(241, 245, 249)
    pdf.cell(132, 6, "TOTALES (RECIBIDO FISICO / OC / DIFERENCIA)", border=1, align="R", fill=True)
    pdf.cell(20, 6, str(total_general_unidades), border=1, align="C", fill=True)
    pdf.cell(19, 6, str(total_oc_general), border=1, align="C", fill=True)
    pdf.cell(19, 6, f"{total_general_unidades - total_oc_general:+d}", border=1, align="C", fill=True, ln=True)

    # --- FIRMAS AL FINAL ---
    pdf.ln(16)
    y_firma = pdf.get_y()
    if y_firma > 250:
        pdf.add_page()
        y_firma = 40
    pdf.line(20, y_firma + 15, 85, y_firma + 15)
    pdf.line(125, y_firma + 15, 190, y_firma + 15)
    pdf.set_xy(20, y_firma + 17)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(65, 5, "RECEPCION BODEGA", align="C")
    pdf.set_xy(125, y_firma + 17)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(65, 5, "ASEGURAMIENTO DE CALIDAD (QA)", align="C")

    oc_limpio = _nombre_archivo_seguro(oc_num)
    prov_limpio = _nombre_archivo_seguro(proveedor)[:25]

    archivo_salida = os.path.join(
        "reportes_recepcion",
        f"Acta_OC_{oc_limpio}_{prov_limpio}_{datetime.now().strftime('%d%m%Y_%H%M%S')}.pdf",
    )
    pdf.output(archivo_salida)
    return archivo_salida


def generar_pdf_totem_rack(pasillo: str, columna: str, niveles: int = 5):
    os.makedirs("temp_qrs", exist_ok=True)
    os.makedirs("reportes_recepcion", exist_ok=True)
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False, margin=0)
    pdf.add_page()

    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, 210, 22, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(0, 6)
    pdf.cell(210, 10, txt=f"TOTEM DE UBICACIONES | PASILLO {pasillo} - COLUMNA {columna}", align="C")
    pdf.set_text_color(0, 0, 0)

    y_pos = 30
    for niv in range(niveles, 0, -1):
        cod_ubi = f"{pasillo.upper().strip()}-{columna.upper().strip()}-N{niv}"
        qr_path = f"temp_qrs/{cod_ubi}.png"
        qrcode.make(cod_ubi).save(qr_path)

        pdf.set_draw_color(180, 180, 180)
        pdf.rect(15, y_pos, 180, 46)
        pdf.image(qr_path, x=22, y=y_pos + 3, w=40)

        pdf.set_font("Helvetica", "B", 26)
        pdf.set_xy(70, y_pos + 8)
        pdf.cell(115, 14, txt=cod_ubi, align="L")

        tipo_nivel = "NIVEL PICKING / REAPRO" if niv == 1 else f"NIVEL RESERVA ALTURA {niv}"
        pdf.set_font("Helvetica", "", 11)
        pdf.set_xy(70, y_pos + 25)
        pdf.cell(115, 10, txt=f"{tipo_nivel} | Escanear QR con Terminal RF", align="L")
        y_pos += 50

    nombre_archivo = os.path.join("reportes_recepcion", f"Totem_{pasillo}_{columna}.pdf")
    pdf.output(nombre_archivo)
    if os.name == "nt":
        try:
            os.startfile(nombre_archivo)
        except Exception:
            pass
    return nombre_archivo


def generar_pdf_etiqueta_ubicacion_individual(codigo_ubicacion: str, zona: str = "RACK"):
    os.makedirs("temp_qrs", exist_ok=True)
    os.makedirs("reportes_recepcion", exist_ok=True)
    cod_limpio = codigo_ubicacion.strip().upper()
    qr_path = f"temp_qrs/UBI_{cod_limpio}.png"
    qrcode.make(cod_limpio).save(qr_path)

    pdf = FPDF(orientation="L", unit="mm", format=(100, 150))
    pdf.set_auto_page_break(auto=False, margin=0)
    pdf.add_page()

    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, 150, 16, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(0, 4)
    pdf.cell(150, 8, txt=f"LUDIPEK WMS - POSICION DE BODEGA ({zona})", align="C")
    pdf.set_text_color(0, 0, 0)

    pdf.set_font("Helvetica", "B", 36)
    pdf.set_xy(5, 32)
    pdf.cell(92, 20, txt=cod_limpio, align="C")

    pdf.set_font("Helvetica", "", 12)
    pdf.set_xy(5, 60)
    pdf.cell(92, 10, txt="UBICACION OFICIAL CERTIFICADA", align="C")

    pdf.image(qr_path, x=100, y=22, w=44)
    pdf.rect(0.5, 0.5, 149, 99)

    nombre_archivo = os.path.join("reportes_recepcion", f"Ubicacion_{cod_limpio}.pdf")
    pdf.output(nombre_archivo)
    if os.name == "nt":
        try:
            os.startfile(nombre_archivo)
        except Exception:
            pass
    return nombre_archivo


# =====================================================================
# 5. COMPONENTES VISUALES Y GRAFICOS BI NATIVOS
# =====================================================================
def generar_pdf_ubicaciones_vacias(lista_vacias: list):
    os.makedirs("reportes_inventario", exist_ok=True)
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, 210, 22, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(0, 6)
    pdf.cell(210, 10, txt="LUDIPEK WMS - REPORTE DE UBICACIONES Y ESPACIOS VACIOS", align="C")
    pdf.set_text_color(0, 0, 0)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(10, 26)
    pdf.cell(190, 6, txt=f"Fecha de Generación: {datetime.now().strftime('%d-%m-%Y %H:%M')}", align="R")

    pdf.set_xy(10, 35)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(226, 232, 240)
    pdf.cell(40, 8, "ZONA / PASILLO", border=1, fill=True, align="C")
    pdf.cell(60, 8, "CODIGO UBICACION", border=1, fill=True, align="C")
    pdf.cell(90, 8, "OBSERVACION DE INSPECCION", border=1, fill=True, align="C")
    pdf.ln(8)

    pdf.set_font("Helvetica", "", 10)
    for ubi in sorted(lista_vacias):
        zona = ubi.split("-")[0] if "-" in ubi else "S/Z"
        pdf.set_x(10)
        pdf.cell(40, 8, zona, border=1, align="C")
        pdf.cell(60, 8, ubi, border=1, align="C")
        pdf.cell(90, 8, "", border=1, align="L")
        pdf.ln(8)

    nombre_archivo = os.path.join("reportes_inventario", f"Ubicaciones_Vacias_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf")
    pdf.output(nombre_archivo)
    if os.name == "nt":
        try:
            os.startfile(nombre_archivo)
        except Exception:
            pass
    return nombre_archivo


def separador_vertical():
    return ft.Container(
        width=1,
        height=30,
        bgcolor=ft.Colors.BLUE_GREY_200,
        margin=ft.Margin.symmetric(horizontal=6),
    )


def campo_texto(label: str, width: int = None, expand=None, value: str = "", keyboard_type=None, on_change=None):
    return ft.TextField(
        label=label,
        width=width,
        expand=expand,
        value=value,
        dense=True,
        text_size=12,
        label_style=ft.TextStyle(size=11),
        content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
        keyboard_type=keyboard_type,
        on_change=on_change,
        border_radius=6,
    )


def campo_dropdown(label: str, width: int = None, expand=None, value: str = None, options: list = None):
    return ft.Dropdown(
        label=label,
        width=width,
        expand=expand,
        value=value,
        options=options or [],
        dense=True,
        text_size=12,
        label_style=ft.TextStyle(size=11),
        content_padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border_radius=6,
    )


def crear_tarjeta(contenido, padding=14, expand_val=None, height_val=None, bgcolor_val=ft.Colors.WHITE, lista_registro=None):
    c = ft.Container(
        content=contenido,
        padding=padding,
        height=height_val,
        expand=expand_val,
        bgcolor=bgcolor_val,
        border_radius=8,
        border=ft.Border.all(1, "#E2E8F0"),
        shadow=ft.BoxShadow(
            spread_radius=0,
            blur_radius=8,
            color=ft.Colors.BLACK_12,
            offset=ft.Offset(0, 2),
        ),
    )
    if lista_registro is not None:
        lista_registro.append(c)
    return c


def crear_kpi_card(
    titulo: str,
    txt_valor_control: ft.Text,
    subtitulo: str,
    color_icono: str,
    bg_icono: str,
    icono,
    lista_registro=None,
):
    box_icono = ft.Container(
        content=ft.Icon(icono, color=color_icono, size=22),
        bgcolor=bg_icono,
        padding=10,
        border_radius=8,
    )
    card = ft.Container(
        expand=1,
        padding=12,
        bgcolor=ft.Colors.WHITE,
        border_radius=8,
        border=ft.Border.all(1, "#E2E8F0"),
        content=ft.Row(
            [
                box_icono,
                ft.Column(
                    [
                        ft.Text(titulo.upper(), size=10, color="#475569", weight=ft.FontWeight.BOLD),
                        txt_valor_control,
                        ft.Text(subtitulo, size=10, color="#64748B"),
                    ],
                    spacing=1,
                ),
            ],
            spacing=10,
        ),
    )
    if lista_registro is not None:
        lista_registro.append((card, box_icono, txt_valor_control))
    return card


def crear_badge_estado(texto: str, color_texto: str, color_fondo: str):
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=9, vertical=3),
        bgcolor=color_fondo,
        border_radius=4,
        content=ft.Text(texto.upper(), color=color_texto, size=10, weight=ft.FontWeight.BOLD),
    )


def boton_primario(texto: str, icono, evento, color="#1E3A8A", disabled=False, height_val=35):
    return ft.Button(
        content=ft.Text(texto, size=11, weight=ft.FontWeight.BOLD),
        icon=icono,
        bgcolor=color,
        color=ft.Colors.WHITE,
        on_click=evento,
        disabled=disabled,
        height=height_val,
        style=ft.ButtonStyle(
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            shape=ft.RoundedRectangleBorder(radius=6),
        ),
    )


TABLAS_SCROLL_ADAPTABLES = []


def envolver_tabla_scroll(tabla: ft.DataTable, altura_inicial: int):
    # Compactar márgenes de la tabla para que quepan todas las columnas y botones sin cortarse
    tabla.column_spacing = min(getattr(tabla, "column_spacing", 14) or 14, 12)
    tabla.horizontal_margin = 8

    cont = ft.Container(
        height=altura_inicial,
        padding=ft.Padding.only(right=8, bottom=6),
        content=ft.Column(
            [
                ft.Row(
                    [tabla],
                    scroll=ft.ScrollMode.ALWAYS,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            ],
            scroll=ft.ScrollMode.ALWAYS,
            expand=True,
        ),
    )
    # Mantener acotado el buffer global en caso de llamadas fuera del ciclo de inicio
    if len(TABLAS_SCROLL_ADAPTABLES) > 250:
        del TABLAS_SCROLL_ADAPTABLES[:100]
    TABLAS_SCROLL_ADAPTABLES.append((cont, altura_inicial))
    return cont


def barra_horizontal_bi(etiqueta: str, valor: float, max_val: float, sufijo: str, color_barra: str):
    pct = min(1.0, max(0.05, valor / max(0.1, max_val)))
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Text(etiqueta, size=11, weight=ft.FontWeight.W_600, color="#1E293B"),
                    ft.Text(f"{valor:.1f} {sufijo}", size=11, weight=ft.FontWeight.BOLD, color=color_barra),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.ProgressBar(value=pct, height=8, color=color_barra, bgcolor="#E2E8F0", border_radius=4),
        ],
        spacing=3,
    )


def barra_apilada_turno(sector: str, manana_un: int, tarde_un: int, max_total: int):
    total = max(1, manana_un + tarde_un)
    ancho_total_pct = min(1.0, total / max(1, max_total))
    flex_m = max(1, int((manana_un / total) * 100))
    flex_t = max(1, 100 - flex_m)
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Text(sector, size=11, weight=ft.FontWeight.BOLD, color="#0F172A"),
                    ft.Text(f"Mañana: {manana_un} UN  |  Tarde: {tarde_un} UN  (Total: {total})", size=10, color="#475569"),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Container(
                height=12,
                border_radius=4,
                bgcolor="#F1F5F9",
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=ft.Row(
                    [
                        ft.Container(expand=int(flex_m * ancho_total_pct), bgcolor="#1D4ED8", tooltip=f"Turno Mañana: {manana_un} UN"),
                        ft.Container(expand=int(flex_t * ancho_total_pct), bgcolor="#0D9488", tooltip=f"Turno Tarde: {tarde_un} UN"),
                        ft.Container(expand=max(0, int(100 * (1.0 - ancho_total_pct))), bgcolor="#E2E8F0"),
                    ],
                    spacing=0,
                ),
            ),
        ],
        spacing=3,
    )


# =====================================================================
# 6. APLICACION PRINCIPAL - TORRE DE CONTROL BI & WMS
# =====================================================================
_COLORES_ERROR = {"#B91C1C", "#DC2626", "#991B1B", "#EF4444", "#7F1D1D", "RED"}


def notificar_global(page, texto: str, color: str = "#1E3A8A"):
    import flet as ft
    # Los avisos en rojo son fallas: quedan también en el registro central (módulo Desarrollador)
    if str(color or "").upper() in _COLORES_ERROR:
        registrar_error_pc(CONTEXTO_ERRORES_PC.get("modulo") or "PC", str(texto or ""))
    # Sesión del PC vencida o cerrada: volver al login en vez de mostrar errores en cada pantalla
    al_vencer = getattr(page, "_al_vencer_sesion_pc", None)
    if ("SESION_PC_REQUERIDA" in str(texto) or "SESION_EXPIRADA" in str(texto)) and al_vencer:
        try:
            al_vencer()
        except Exception:
            pass
        texto = "Su sesión del PC venció o fue cerrada. Vuelva a ingresar con su usuario y contraseña."
        color = "#B45309"
    page.show_dialog(
        ft.SnackBar(
            content=ft.Text(texto, color=ft.Colors.WHITE, weight=ft.FontWeight.W_600, size=12),
            bgcolor=color,
        )
    )
    page.update()


def mostrar_aviso_ingreso_modal_global(page, lpn_str: str, sku_str: str, unid_str: str, lote_str: str, qa_str: str):
    import flet as ft
    from datetime import datetime
    dialogo_ingreso = ft.AlertDialog(
        modal=False,
        title=ft.Row(
            [
                ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED, color="#1E3A8A"),
                ft.Text("AVISO OFICIAL DE INGRESO EN ANDEN", size=15, weight=ft.FontWeight.BOLD),
            ],
            spacing=10,
        ),
        content=ft.Container(
            width=420,
            padding=12,
            bgcolor="#F8FAFC",
            border_radius=6,
            content=ft.Column(
                [
                    ft.Text(f"IDENTIFICADOR LPN: {lpn_str}", weight=ft.FontWeight.BOLD, size=14),
                    ft.Text(f"ARTICULO (SKU): {sku_str}", size=13),
                    ft.Text(f"CANTIDAD INGRESADA: {unid_str} UNIDADES", size=13, weight=ft.FontWeight.W_600),
                    ft.Text(f"LOTE REGISTRADO: {lote_str}", size=13),
                    ft.Text(f"DICTAMEN CALIDAD (QA): {qa_str}", size=13, weight=ft.FontWeight.BOLD),
                    ft.Text(f"TIMESTAMP: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}", size=11, color="#64748B"),
                ],
                tight=True,
                spacing=6,
            ),
        ),
        actions=[ft.Button("CONFIRMAR LECTURA", on_click=lambda e: page.pop_dialog())],
    )
    page.show_dialog(dialogo_ingreso)
    page.update()


def reimprimir_desde_fila_global(page, lpn_cod: str):
    try:
        res = supabase.table("registro_recepcion").select("*").eq("lpn", lpn_cod).execute()
        if res.data:
            ruta = generar_pdf_recepcion_15x10(lpn_cod, res.data)
            descargar_o_abrir_archivo(page, ruta)
            notificar_global(page, f"Etiqueta LPN {lpn_cod} generada correctamente.", "#047857")
        else:
            notificar_global(page, f"No se encontró el LPN {lpn_cod}.", "#D97706")
    except Exception as ex:
        notificar_global(page, f"Error al generar documento para {lpn_cod}: {ex}", "#B91C1C")


def hash_password_seguro(password_plana: str) -> str:
    salt = os.getenv("WMS_PASSWORD_SALT", "ludipek_wms_salt_2026")
    return "sha256$" + hashlib.sha256(f"{salt}:{password_plana}".encode("utf-8")).hexdigest()


def verificar_password_seguro(password_ingresada: str, password_guardada: str) -> bool:
    if not password_ingresada or not password_guardada:
        return False
    ing = password_ingresada.strip()
    gua = str(password_guardada).strip()
    if gua.startswith("sha256$"):
        return hmac.compare_digest(hash_password_seguro(ing), gua)
    return hmac.compare_digest(ing, gua)


def descargar_o_abrir_archivo(page: ft.Page, ruta_archivo: str):
    """Abre el archivo localmente en Windows (os.startfile) y publica botón de descarga directa en SnackBar para Web."""
    if not ruta_archivo or not os.path.exists(ruta_archivo):
        if page is not None:
            notificar_global(page, "No se encontró el archivo generado para descargar.", "#B91C1C")
        return
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        carpeta_pub = os.path.join(base_dir, "assets", "descargas")
        os.makedirs(carpeta_pub, exist_ok=True)

        nombre_orig = os.path.basename(ruta_archivo)
        base_nom, ext_nom = os.path.splitext(nombre_orig)
        nombre_seguro = f"{_nombre_archivo_seguro(base_nom)}{ext_nom.lower()}"
        destino_pub = os.path.join(carpeta_pub, nombre_seguro)

        if os.path.abspath(ruta_archivo) != os.path.abspath(destino_pub):
            shutil.copy2(ruta_archivo, destino_pub)

        # También copiar a carpeta relativa assets/descargas por si el servidor se inició desde otro directorio
        carpeta_rel = os.path.join("assets", "descargas")
        os.makedirs(carpeta_rel, exist_ok=True)
        destino_rel = os.path.join(carpeta_rel, nombre_seguro)
        if os.path.abspath(destino_pub) != os.path.abspath(destino_rel):
            shutil.copy2(ruta_archivo, destino_rel)

        # En Windows local (Escritorio), abrir directamente con os.startfile
        if os.name == "nt" and not getattr(page, "web", False):
            try:
                os.startfile(os.path.abspath(ruta_archivo))
            except Exception:
                pass

        url_rel = f"/descargas/{urllib.parse.quote(nombre_seguro)}"

        if page is not None:
            snack_dl = ft.SnackBar(
                bgcolor="#0F172A",
                duration=8000,
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.CLOUD_DONE_ROUNDED, color="#34D399", size=20),
                        ft.Text(
                            f"Listo: {nombre_seguro}",
                            color=ft.Colors.WHITE,
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            expand=True,
                        ),
                        ft.TextButton(
                            content=ft.Row(
                                [
                                    ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, color=ft.Colors.WHITE, size=16),
                                    ft.Text("DESCARGAR AQUÍ", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                                ],
                                spacing=6,
                                tight=True,
                            ),
                            url=url_rel,
                            style=ft.ButtonStyle(
                                bgcolor="#047857",
                                padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                                shape=ft.RoundedRectangleBorder(radius=6),
                            ),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            )
            page.show_dialog(snack_dl)
            page.update()
    except Exception as ex_dl:
        print(f"[WARN] Error enviando archivo al navegador: {ex_dl}")


# =====================================================================
# 10. SISTEMA RESPONSIVE Y NAVEGACION LIMPIA PARA WMS PC
# =====================================================================
def obtener_perfil_responsive(page: ft.Page) -> dict:
    """Contrato visual compartido para notebook, escritorio y monitor externo."""
    ancho = float(page.width or 1366)
    alto = float(page.height or 768)
    if ancho < 1100:
        modo, menu, maximo, columnas = "compacto", 68, ancho, 1
    elif ancho < 1440:
        modo, menu, maximo, columnas = "notebook", 190, 1400, 2
    elif ancho < 1920:
        modo, menu, maximo, columnas = "escritorio", 215, 1600, 3
    else:
        modo, menu, maximo, columnas = "amplio", 225, 1720, 4
    return {
        "modo": modo,
        "ancho": ancho,
        "alto": alto,
        "menu_width": menu,
        "content_max": maximo,
        "columnas": columnas,
        "padding": 6 if modo == "compacto" else (8 if modo == "notebook" else 12),
        "card_padding": 8 if modo in ("compacto", "notebook") else 12,
        "table_factor": 0.68 if alto < 760 else (0.82 if alto < 900 else 1.0),
        "compacto": modo == "compacto",
    }


def aplicar_responsive_a_vista(vista, perfil: dict):
    """Aplica densidad y ancho estable sin tocar reglas de negocio del modulo."""
    if vista is None:
        return
    try:
        vista.padding = perfil["padding"]
        # Ancho = espacio realmente disponible (pantalla - menú lateral), con tope en monitores grandes.
        # Antes era fijo (1180 px en notebook) y junto al menú superaba una pantalla de 1366 px.
        disponible = int(perfil["ancho"] - perfil["menu_width"] - 12)
        vista.width = max(340, min(perfil["content_max"], disponible))
        vista.expand = False
        vista.alignment = ft.Alignment.TOP_CENTER
        if isinstance(getattr(vista, "content", None), ft.Column):
            vista.content.scroll = ft.ScrollMode.AUTO
            vista.content.expand = True
    except Exception:
        pass


def cerrar_superficies_transitorias(page: ft.Page):
    """Cierra dialogos/snackbars al cambiar de modulo sin borrar datos persistidos."""
    try:
        # Flet 0.70+: los diálogos se cierran con pop_dialog() (close_dialog no existe).
        page.pop_dialog()
    except Exception:
        try:
            if getattr(page, "dialog", None):
                page.dialog.open = False
        except Exception:
            pass
    try:
        if getattr(page, "snack_bar", None):
            page.snack_bar.open = False
    except Exception:
        pass


# WMS PRO: contrato compartido
try:
 from dominio.estados import EstadoWms, EstadoNetSuite, EstadoRecepcion, validar_transicion
 from dominio.errores import WmsError, WmsDataError, SupabaseWriteError, ConciliacionError
 from servicios.normalizacion import normalizar_sku, normalizar_lote, fecha_a_date, fecha_a_iso, fecha_a_visual, lote_fecha_visual, normalizar_bodega
 from servicios.conversion_empaque import convertir_unidades, calcular_unidades, seleccionar_presentaciones
 WMS_PRO_DISPONIBLE=True
except Exception as _wms_pro_error:
 WMS_PRO_DISPONIBLE=False
 print(f"[WARN] Servicios WMS Pro no disponibles: {_wms_pro_error}")


# =====================================================================
# 11. SISTEMA VISUAL LUDIPEK (componentes compartidos por todos los módulos)
#     Un solo estilo de botón, tarjeta, KPI y menú de acciones.
# =====================================================================
UI = {
    "bg": "#1B2122",
    "card": "#232B2D",
    "card_alt": "#1D2426",
    "input": "#1D2426",
    "borde": "#334044",
    "texto": "#F1F5F9",
    "texto_2": "#94A3B8",
    "texto_3": "#64748B",
    "primario": "#0284C7",
    "acento": "#38BDF8",
    "exito": "#10B981",
    "alerta": "#F59E0B",
    "peligro": "#DC2626",
}


def ui_boton(texto: str, icono=None, on_click=None, tipo: str = "primario", tooltip: str = None,
             disabled: bool = False, expand=None):
    """tipo: 'primario' (acción principal, 1 por pantalla), 'secundario', 'peligro' o 'texto'."""
    contenido = ft.Text(texto, size=12, weight=ft.FontWeight.W_600)
    forma = ft.RoundedRectangleBorder(radius=6)
    relleno = ft.Padding.symmetric(horizontal=14, vertical=8)
    if tipo == "secundario":
        return ft.OutlinedButton(
            content=contenido, icon=icono, on_click=on_click, tooltip=tooltip, disabled=disabled, expand=expand,
            height=36,
            style=ft.ButtonStyle(shape=forma, padding=relleno, color=UI["texto"],
                                 side=ft.BorderSide(1, UI["borde"]), icon_color=UI["acento"]),
        )
    if tipo == "texto":
        return ft.TextButton(
            content=contenido, icon=icono, on_click=on_click, tooltip=tooltip, disabled=disabled, expand=expand,
            height=36, style=ft.ButtonStyle(shape=forma, padding=relleno, color=UI["acento"]),
        )
    return ft.Button(
        content=contenido, icon=icono, on_click=on_click, tooltip=tooltip, disabled=disabled, expand=expand,
        height=36, bgcolor=UI["peligro"] if tipo == "peligro" else UI["primario"], color=ft.Colors.WHITE,
        style=ft.ButtonStyle(shape=forma, padding=relleno),
    )


def ui_menu(texto: str, icono, items: list, tooltip: str = None):
    """Botón con menú desplegable. items: (texto, icono, on_click) o None para un separador."""
    entradas = []
    for it in items:
        if it is None:
            entradas.append(ft.PopupMenuItem())
            continue
        txt, ico, fn = it[0], it[1], it[2]
        peligro = len(it) > 3 and it[3]
        entradas.append(ft.PopupMenuItem(
            content=ft.Row([
                ft.Icon(ico, size=18, color=UI["peligro"] if peligro else UI["acento"]),
                ft.Text(txt, size=12, color=UI["peligro"] if peligro else None),
            ], spacing=10),
            on_click=fn,
        ))
    return ft.PopupMenuButton(
        tooltip=tooltip or texto,
        items=entradas,
        content=ft.Container(
            height=36,
            padding=ft.Padding.symmetric(horizontal=12, vertical=0),
            border=ft.Border.all(1, UI["borde"]),
            border_radius=6,
            content=ft.Row([
                ft.Icon(icono, size=18, color=UI["acento"]),
                ft.Text(texto, size=12, weight=ft.FontWeight.W_600, color=UI["texto"]),
                ft.Icon(ft.Icons.ARROW_DROP_DOWN_ROUNDED, size=18, color=UI["texto_2"]),
            ], spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ),
    )


def ui_encabezado(titulo: str, subtitulo: str = None, icono=None, acciones: list = None):
    """Encabezado de pantalla: título a la izquierda, acciones a la derecha (bajan de línea si no caben)."""
    bloque_titulo = ft.Row([
        *([ft.Icon(icono, size=24, color=UI["acento"])] if icono else []),
        ft.Column([
            ft.Text(titulo, size=18, weight=ft.FontWeight.W_700, color=UI["texto"]),
            *([ft.Text(subtitulo, size=12, color=UI["texto_2"])] if subtitulo else []),
        ], spacing=1, tight=True),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return ft.Row(
        [bloque_titulo, ft.Row(acciones or [], spacing=8, wrap=True, run_spacing=8)],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        wrap=True,
        run_spacing=10,
    )


def ui_tarjeta(contenido, titulo: str = None, subtitulo: str = None, acciones: list = None, icono=None,
               padding: int = 16, expand=None, col=None):
    """Tarjeta estándar. 'col' permite usarla dentro de ft.ResponsiveRow."""
    partes = []
    if titulo:
        partes.append(ft.Row([
            ft.Row([
                *([ft.Icon(icono, size=18, color=UI["acento"])] if icono else []),
                ft.Column([
                    ft.Text(titulo, size=14, weight=ft.FontWeight.W_600, color=UI["texto"]),
                    *([ft.Text(subtitulo, size=11, color=UI["texto_2"])] if subtitulo else []),
                ], spacing=1, tight=True),
            ], spacing=8),
            ft.Row(acciones or [], spacing=8, wrap=True, run_spacing=8),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True, run_spacing=8))
    partes.append(contenido)
    return ft.Container(
        content=ft.Column(partes, spacing=12, tight=True),
        padding=padding,
        bgcolor=UI["card"],
        border_radius=10,
        border=ft.Border.all(1, UI["borde"]),
        expand=expand,
        col=col,
    )


def ui_kpi(valor: ft.Text, etiqueta: str, icono, color: str, detalle: ft.Text = None, col=None):
    """Indicador: valor grande, etiqueta y detalle opcional. Usar dentro de ft.ResponsiveRow."""
    valor.size = 24
    valor.weight = ft.FontWeight.W_700
    valor.color = UI["texto"]
    valor.font_family = None
    return ft.Container(
        col=col or {"xs": 12, "sm": 6, "md": 6, "lg": 3},
        padding=14,
        bgcolor=UI["card"],
        border_radius=10,
        border=ft.Border(left=ft.BorderSide(3, color), top=ft.BorderSide(1, UI["borde"]),
                         right=ft.BorderSide(1, UI["borde"]), bottom=ft.BorderSide(1, UI["borde"])),
        content=ft.Row([
            ft.Container(
                width=40, height=40, border_radius=8, bgcolor=ft.Colors.with_opacity(0.15, color),
                alignment=ft.Alignment.CENTER, content=ft.Icon(icono, size=22, color=color),
            ),
            ft.Column([
                ft.Text(etiqueta, size=11, color=UI["texto_2"], weight=ft.FontWeight.W_500),
                valor,
                *([detalle] if detalle else []),
            ], spacing=0, tight=True, expand=True),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def ui_tabla(tabla: ft.DataTable, altura: int = 360):
    """Tabla con encabezado fijo de estilo, scroll vertical y horizontal (nunca se corta)."""
    tabla.heading_row_color = UI["card_alt"]
    tabla.column_spacing = 18
    tabla.horizontal_margin = 12
    tabla.divider_thickness = 0.5
    cont = ft.Container(
        height=altura,
        border=ft.Border.all(1, UI["borde"]),
        border_radius=8,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Column(
            [ft.Row([tabla], scroll=ft.ScrollMode.AUTO, vertical_alignment=ft.CrossAxisAlignment.START)],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
    )
    TABLAS_SCROLL_ADAPTABLES.append((cont, altura))
    return cont


def ui_pestanas(opciones: list, al_cambiar, seleccion: int = 0):
    """Selector de vistas dentro de una pantalla (estilo pestañas). opciones: [(texto, icono)]."""
    fila = ft.Row(spacing=4, wrap=True)

    def construir(activo: int):
        fila.controls = []
        for i, (txt, ico) in enumerate(opciones):
            sel = i == activo
            fila.controls.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=14, vertical=8),
                border_radius=6,
                bgcolor=ft.Colors.with_opacity(0.15, UI["acento"]) if sel else None,
                border=ft.Border(bottom=ft.BorderSide(2, UI["acento"] if sel else "transparent")),
                ink=True,
                on_click=lambda e, idx=i: (construir(idx), al_cambiar(idx)),
                content=ft.Row([
                    ft.Icon(ico, size=16, color=UI["acento"] if sel else UI["texto_2"]),
                    ft.Text(txt, size=12, weight=ft.FontWeight.W_600, color=UI["texto"] if sel else UI["texto_2"]),
                ], spacing=6, tight=True),
            ))

    construir(seleccion)
    fila.data = construir  # permite re-marcar desde código: fila.data(idx)
    return fila
