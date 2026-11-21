"""Acta de recepción de un traslado Santiago -> Concepción (PDF, reportlab).

Mismo contenido que el acta que genera el celular de Concepción al cerrar la OT: resumen,
enviado vs recibido por pallet y SKU (con lotes y vencimientos), diferencias destacadas,
motivos y firmas. Recibe el resultado de wms_traslado_ccp_detalle.
"""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

AZUL = colors.HexColor("#1E3A8A")
AMBAR = colors.HexColor("#B45309")
ROJO = colors.HexColor("#B91C1C")
VERDE = colors.HexColor("#047857")
FONDO_DIF = colors.HexColor("#FEF3C7")
GRIS = colors.HexColor("#F1F5F9")

NOMBRE_ESTADO = {
    "RECIBIDO_CCP": "RECIBIDA CONFORME",
    "RECIBIDO_CCP_CON_DIFERENCIAS": "RECIBIDA CON DIFERENCIAS",
    "RECEPCION_CCP_EN_PROCESO": "EN RECEPCIÓN (PARCIAL)",
    "EN_TRANSITO_CCP": "EN TRÁNSITO",
}


def _n(v) -> int:
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def _fecha(v) -> str:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        try:
            from zoneinfo import ZoneInfo
            d = d.astimezone(ZoneInfo("America/Santiago"))
        except Exception:
            pass
        return d.strftime("%d-%m-%Y %H:%M")
    except Exception:
        return "-"


def generar_pdf_acta_traslado(det: dict, usuario: str = "") -> bytes:
    pallets = list(det.get("pallets") or [])
    estado = str(det.get("estado") or "")
    p_txt = ParagraphStyle("t", fontName="Helvetica", fontSize=7.5, leading=9)
    p_tit = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=15, leading=18)
    p_sub = ParagraphStyle("s", fontName="Helvetica", fontSize=9, leading=11, textColor=colors.grey)
    p_mot = ParagraphStyle("m", fontName="Helvetica", fontSize=8.5, leading=11)

    filas = [["Pallet", "SKU", "Descripción", "Lote / venc. enviado", "Enviado", "Lote / venc. recibido", "Recibido", "Dif.",
              "Resultado"]]
    dif_rows = []
    env_un = rec_un = env_cj = p_dif = p_no = 0
    for p in pallets:
        est = str(p.get("estado") or "")
        p_no += est == "NO_LLEGO"
        p_dif += est == "RECIBIDO_CON_DIFERENCIAS"
        for l in p.get("lineas") or []:
            env = _n(l.get("unidades"))
            rec = 0 if est == "NO_LLEGO" else _n(l.get("unidades_recibidas"))
            env_un += env
            rec_un += rec
            env_cj += _n(l.get("cajas"))
            res = "NO LLEGÓ" if est == "NO_LLEGO" else str(l.get("resultado") or "PENDIENTE").replace("_", " ")
            if l.get("partes"):
                lote_rec = " + ".join(f"{x.get('lote')} / {x.get('vencimiento') or 'S/F'} ({x.get('unidades')})"
                                      for x in l.get("partes"))
            elif l.get("lote_recibido") is None:
                lote_rec = "-"
            else:
                lote_rec = f"{l.get('lote_recibido')} / {l.get('vencimiento_recibido') or 'S/F'}"
            dif = rec - env
            if res != "CONFORME":
                dif_rows.append(len(filas))
            lpn = str(p.get("lpn") or "")
            if p.get("lpn_destino") and p.get("lpn_destino") != p.get("lpn"):
                lpn += f"<br/>-> {p.get('lpn_destino')}"
            filas.append([
                Paragraph(lpn, p_txt), str(l.get("sku") or ""), Paragraph(str(l.get("descripcion") or "")[:60], p_txt),
                Paragraph(f"{l.get('lote') or 'S/L'} / {l.get('vencimiento') or 'S/F'}", p_txt), str(env),
                Paragraph(lote_rec, p_txt), str(rec), f"{dif:+d}" if dif else "0", Paragraph(res, p_txt),
            ])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=10 * mm, bottomMargin=12 * mm,
                            title=f"Acta de recepción {det.get('numero_ot') or ''}")
    con_dif = "DIFERENCIAS" in estado or bool(dif_rows) or p_no > 0
    color_estado = AMBAR if con_dif else VERDE
    fechas = sorted(_fecha(p.get("fecha")) for p in pallets if p.get("fecha"))
    receptores = ", ".join(sorted({str(p.get("usuario")) for p in pallets if p.get("usuario")}))

    cab = Table([[Paragraph("ACTA DE RECEPCIÓN DE TRASLADO", p_tit),
                  Paragraph(f"Bodega Santiago -> Bodega Concepción<br/>Emitida {datetime.now().strftime('%d-%m-%Y %H:%M')}"
                            + (f" por {usuario}" if usuario else ""), p_sub)]], colWidths=[150 * mm, 120 * mm])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))

    franja = Table([[str(det.get("numero_ot") or ""), NOMBRE_ESTADO.get(estado, estado),
                     f"Recibido: {fechas[-1] if fechas else '-'}" + (f" · {receptores}" if receptores else "")]],
                   colWidths=[80 * mm, 90 * mm, 103 * mm])
    franja.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (0, 0), 15), ("FONTSIZE", (1, 0), (2, 0), 11),
        ("TEXTCOLOR", (1, 0), (1, 0), color_estado), ("BOX", (0, 0), (-1, -1), 1.5, color_estado),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    dif_un = rec_un - env_un
    kpis = Table([["Pallets", "Con diferencias", "No llegaron", "Cajas enviadas", "Unidades enviadas", "Unidades recibidas",
                   "Diferencia (UN)"],
                  [str(len(pallets)), str(p_dif), str(p_no), str(env_cj), str(env_un), str(rec_un), f"{dif_un:+d}" if dif_un else "0"]],
                 colWidths=[39 * mm] * 7)
    kpis.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GRIS), ("FONTSIZE", (0, 0), (-1, 0), 7.5), ("TEXTCOLOR", (0, 0), (-1, 0), colors.grey),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"), ("FONTSIZE", (0, 1), (-1, 1), 13),
        ("TEXTCOLOR", (1, 1), (1, 1), AMBAR if p_dif else colors.black), ("TEXTCOLOR", (2, 1), (2, 1), ROJO if p_no else colors.black),
        ("TEXTCOLOR", (5, 1), (6, 1), ROJO if dif_un else VERDE),
        ("LINEAFTER", (0, 0), (-2, -1), 2, colors.white), ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))

    tabla = Table(filas, repeatRows=1, colWidths=[30 * mm, 20 * mm, 55 * mm, 34 * mm, 15 * mm, 58 * mm, 15 * mm, 13 * mm, 30 * mm])
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (4, 1), (4, -1), "RIGHT"), ("ALIGN", (6, 1), (7, -1), "RIGHT"),
    ]
    for r in dif_rows:
        estilo.append(("BACKGROUND", (0, r), (-1, r), FONDO_DIF))
    tabla.setStyle(TableStyle(estilo))

    for t_ in (cab, franja, kpis, tabla):
        t_.hAlign = "LEFT"
    historia = [cab, Spacer(1, 4 * mm), franja, Spacer(1, 3 * mm), kpis, Spacer(1, 4 * mm), tabla]
    motivos = [f"{p.get('lpn')}: {p.get('observacion')} ({p.get('usuario') or '-'})" for p in pallets if p.get("observacion")]
    if motivos:
        historia += [Spacer(1, 4 * mm), Paragraph("<b>Motivos informados</b>", p_mot)]
        historia += [Paragraph(f"- {m}", p_mot) for m in motivos]
    firmas = Table([["", "", "", "", ""], ["Recibe (Concepción)", "", "Revisa (Supervisor)", "", "Despacha (Santiago)"]],
                   colWidths=[70 * mm, 30 * mm, 70 * mm, 30 * mm, 70 * mm], rowHeights=[16 * mm, 6 * mm])
    firmas.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (0, 0), 0.6, colors.grey), ("LINEBELOW", (2, 0), (2, 0), 0.6, colors.grey),
        ("LINEBELOW", (4, 0), (4, 0), 0.6, colors.grey), ("ALIGN", (0, 1), (-1, 1), "CENTER"),
        ("FONTSIZE", (0, 1), (-1, 1), 8.5), ("TEXTCOLOR", (0, 1), (-1, 1), colors.grey),
    ]))
    firmas.hAlign = "LEFT"
    historia += [Spacer(1, 10 * mm), firmas]

    def pie(canv, d):
        canv.setFont("Helvetica", 7.5)
        canv.setFillColor(colors.grey)
        canv.drawRightString(d.pagesize[0] - 12 * mm, 6 * mm,
                             f"Ludipek WMS · Acta de recepción {det.get('numero_ot') or ''} · página {canv.getPageNumber()}")

    doc.build(historia, onFirstPage=pie, onLaterPages=pie)
    return buf.getvalue()
