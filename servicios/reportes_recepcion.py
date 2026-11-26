"""Envío automático del reporte de recepción física (script 46).

El celular finaliza la recepción de un contenedor y queda un reporte en cola. Este proceso, que
corre en segundo plano en el programa del PC (Render o un PC de la oficina), toma la cola cada
minuto y envía el reporte por correo a los destinatarios activos, con un Excel adjunto.

Requisitos (los mismos del "Enviar acta" de Recepción):
  · SMTP_USER y SMTP_PASS (opcionales SMTP_HOST, SMTP_PORT, SMTP_FROM) en .env o en Render.
  · Llave de servicio de Supabase: SUPABASE_KEY con la llave secreta, o SUPABASE_KEY_SERVICIO
    si el PC usa la llave pública (modo sesión).
Si falta algo, no hace nada (los reportes quedan en cola hasta que algún equipo pueda enviarlos).
Varios equipos pueden tenerlo activo a la vez: la base entrega cada reporte a uno solo.
"""
import io
import os
import smtplib
import socket
import threading
import time
from email.message import EmailMessage

import pandas as pd

_hilo = None
_INTERVALO = 60


def _cliente_servicio():
    try:
        import dependencias as d
    except Exception:
        return None
    llave = os.getenv("SUPABASE_KEY_SERVICIO", "").strip()
    if llave:
        from supabase import create_client
        return create_client(d.SUPABASE_URL, llave)
    if getattr(d, "MODO_CONEXION_PC", "") == "LLAVE_MAESTRA":
        return d._cliente_base
    return None


def _smtp_listo() -> bool:
    return bool(os.getenv("SMTP_USER", "").strip() and os.getenv("SMTP_PASS", "").strip())


def _fecha(v) -> str:
    try:
        from dependencias import formatear_fecha_hora_chile
        return formatear_fecha_hora_chile(v) if v else "—"
    except Exception:
        return str(v or "—")


def armar_correo(rep: dict):
    """Asunto, cuerpo y Excel adjunto (bytes) de un reporte."""
    d = rep.get("datos") or {}
    cont = d.get("contenedor") or rep.get("contenedor") or "SIN CONTENEDOR"
    oc = d.get("numero_oc")
    estado_ns = {"SI": "Sí", "PARCIAL": "Parcial", "NO": "No", "SIN_DATO": "Sin dato", "NO_APLICA": "No aplica (sin OC)"}
    from servicios.reporte_ejecutivo import asunto_recepcion
    asunto = asunto_recepcion("física", oc, " ".join(str(d.get(k) or "") for k in ("codigo_asn", "nota", "nota_oc")),
                              cont, d.get("proveedor"))
    lineas = d.get("lineas") or []
    cruce = d.get("cruce_oc") or []
    dif = [c for c in cruce if int(c.get("recibido") or 0) != int(c.get("esperado") or 0)]
    cuerpo = (
        "Estimados:\n\n"
        f"Se finalizó la recepción física del contenedor {cont}.\n\n"
        f"Bodega: {rep.get('bodega')}\n"
        f"Tiene OC: {'Sí (' + str(oc) + ')' if d.get('tiene_oc') else 'No (recepción libre, se conciliará con la OC)'}\n"
        f"Cargada a NetSuite: {estado_ns.get(d.get('cargada_ns'), d.get('cargada_ns') or '—')}\n"
        f"Recepción: {_fecha(d.get('inicio'))} a {_fecha(d.get('fin'))} · {d.get('operadores') or ''}\n"
        f"Pallets: {d.get('pallets')} · Cajas: {d.get('cajas')} · Unidades: {d.get('unidades')}\n"
        f"Finalizada por: {rep.get('finalizado_por') or ''}\n"
    )
    if cruce:
        cuerpo += ("\nCruce con la OC/PL:\n" + ("\n".join(
            f"  - {c.get('sku')}: esperado {c.get('esperado') or 0} · recibido {c.get('recibido') or 0} "
            f"({int(c.get('recibido') or 0) - int(c.get('esperado') or 0):+d})" for c in dif[:20]) if dif else "  Sin diferencias.") + "\n")
    cuerpo += "\nDetalle por SKU y lote en el Excel adjunto.\n\nLudipek WMS · mensaje automático"

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame([{
            "Contenedor": cont, "OC": oc or "SIN OC", "Proveedor": d.get("proveedor"),
            "Cargada a NetSuite": estado_ns.get(d.get("cargada_ns"), d.get("cargada_ns")),
            "Inicio": _fecha(d.get("inicio")), "Fin": _fecha(d.get("fin")), "Operadores": d.get("operadores"),
            "Pallets": d.get("pallets"), "Cajas": d.get("cajas"), "Unidades": d.get("unidades"),
        }]).to_excel(xw, sheet_name="Resumen", index=False)
        pd.DataFrame([{"SKU": l.get("sku"), "Lote": l.get("lote"), "Vencimiento": l.get("vencimiento"),
                       "Cajas": l.get("cajas"), "Unidades": l.get("unidades"), "Pallets": l.get("pallets"),
                       "Estado": l.get("qa")} for l in lineas] or [{}]).to_excel(xw, sheet_name="Recibido", index=False)
        if cruce:
            pd.DataFrame([{"SKU": c.get("sku"), "Esperado OC": c.get("esperado"), "Packing list": c.get("packing_list"),
                           "Recibido": c.get("recibido"),
                           "Diferencia": int(c.get("recibido") or 0) - int(c.get("esperado") or 0)} for c in cruce]
                         ).to_excel(xw, sheet_name="Cruce OC", index=False)
    from servicios.reporte_ejecutivo import nombre_reporte_recepcion
    nombre = nombre_reporte_recepcion(oc, " ".join(str(d.get(k) or "") for k in ("codigo_asn", "nota", "nota_oc")),
                                      d.get("proveedor"), None if oc else cont)
    return asunto, cuerpo, buf.getvalue(), nombre


def _enviar(para: list, asunto: str, cuerpo: str, adjunto: bytes, nombre: str):
    user, pwd = os.getenv("SMTP_USER", "").strip(), os.getenv("SMTP_PASS", "").strip()
    host = os.getenv("SMTP_HOST", "smtp.office365.com").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = os.getenv("SMTP_FROM", user).strip()
    msg["To"] = ", ".join(para)
    msg.set_content(cuerpo)
    msg.add_attachment(adjunto, maintype="application",
                       subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=nombre)
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, pwd)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)


def procesar_cola(cliente, equipo: str, enviar=_enviar, maximo: int = 10) -> int:
    """Envía hasta `maximo` reportes en cola. Devuelve cuántos se enviaron."""
    enviados = 0
    for _ in range(maximo):
        rep = cliente.rpc("wms_reporte_tomar", {"p_equipo": equipo}).execute().data
        if not rep:
            break
        para = [c for c in (rep.get("destinatarios") or []) if c]
        if not para:
            cliente.rpc("wms_reporte_marcar", {"p_id": rep["id"], "p_ok": False,
                                               "p_error": "No hay destinatarios activos"}).execute()
            break
        try:
            asunto, cuerpo, adj, nombre = armar_correo(rep)
            try:   # Excel con el formato del resumen ejecutivo (script 51); si falla, queda el Excel simple
                import os
                import tempfile
                from servicios.reporte_ejecutivo import reporte_recepcion, nombre_reporte_desde_datos
                d = rep.get("datos") or {}
                datos_r = cliente.rpc("wms_reporte_recepcion", {
                    "p_bodega": rep.get("bodega"), "p_numero_oc": d.get("numero_oc") or None,
                    "p_clave": None if d.get("numero_oc") else rep.get("clave")}).execute().data or {}
                if datos_r.get("lineas"):
                    # asunto con OC y PO, parcial o total según lo que falta recibir de la OC
                    from servicios.reporte_ejecutivo import asunto_recepcion
                    oc_r = [o for o in (datos_r.get("oc") or []) if int(o.get("unidades_oc") or 0)]
                    if datos_r.get("numero_oc") and oc_r:
                        falta = any(int(o.get("unidades_rec_oc") if o.get("unidades_rec_oc") is not None else 0)
                                    < int(o.get("unidades_oc") or 0) for o in oc_r)
                        asunto = asunto_recepcion("parcial" if falta else "total", datos_r.get("numero_oc"),
                                                  " ".join(str(datos_r.get(k) or "") for k in ("codigo_asn", "nota_oc")),
                                                  d.get("contenedor") or rep.get("contenedor"), datos_r.get("proveedor"))
                    if not datos_r.get("numero_oc") and d.get("contenedor"):
                        datos_r = dict(datos_r, solo_contenedor=True, contenedor=d.get("contenedor"))
                    nombre = nombre_reporte_desde_datos(datos_r)
                    ruta_t = os.path.join(tempfile.gettempdir(), nombre)
                    reporte_recepcion(datos_r, ruta_t)
                    with open(ruta_t, "rb") as fh:
                        adj, nombre = fh.read(), os.path.basename(ruta_t)
            except Exception as ex_x:
                print(f"[REPORTES RECEPCION] resumen ejecutivo no generado: {ex_x}")
            enviar(para, asunto, cuerpo, adj, nombre)
            cliente.rpc("wms_reporte_marcar", {"p_id": rep["id"], "p_ok": True, "p_enviado_a": ", ".join(para)}).execute()
            enviados += 1
        except Exception as ex:
            cliente.rpc("wms_reporte_marcar", {"p_id": rep["id"], "p_ok": False, "p_error": str(ex)[:400]}).execute()
    return enviados


def iniciar_envio_automatico():
    """Arranca (una sola vez por programa) el envío automático en segundo plano."""
    global _hilo
    if _hilo is not None or not _smtp_listo():
        return False
    cliente = _cliente_servicio()
    if cliente is None:
        return False
    equipo = f"{socket.gethostname()[:40]}-{os.getpid()}"

    def ciclo():
        while True:
            try:
                procesar_cola(cliente, equipo)
            except Exception as ex:
                print(f"[REPORTES RECEPCION] {ex}")
            time.sleep(_INTERVALO)

    _hilo = threading.Thread(target=ciclo, daemon=True, name="reportes_recepcion")
    _hilo.start()
    return True
