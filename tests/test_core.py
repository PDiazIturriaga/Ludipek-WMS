from servicios.normalizacion import normalizar_lote, fecha_a_iso, fecha_a_visual, lote_fecha_visual
from servicios.conversion_empaque import convertir_unidades, calcular_unidades
from servicios.conciliacion_recepcion import conciliar

def test_fechas_y_lote():
    assert normalizar_lote(' s / l ') == 'S/L'
    assert fecha_a_iso('22/05/2028') == '2028-05-22'
    assert fecha_a_visual('2028-05-22') == '22/05/2028'
    assert lote_fecha_visual('TELH','2028-05-22') == 'TELH / 22/05/2028'

def test_empaque_tres_niveles():
    x=convertir_unidades(401,384,8)
    assert (x.cajas,x.displays,x.unidades_sueltas,x.unidades_totales)==(1,2,1,401)
    assert calcular_unidades(1,2,1,384,8)==401

def test_conciliacion_por_lote():
    oc=[{'sku':'USA601','lote':'TELH','fecha_vencimiento':'2028-05-22','unidades':144}]
    pl=[{'sku':'USA601','lote':'TELH','fecha_vencimiento':'22/05/2028','unidades':144}]
    fis=[{'sku':'USA601','lote':'TELH','fecha_vencimiento':'2028-05-22','unidades':144}]
    r=conciliar(oc,pl,fis)
    assert len(r)==1 and not r[0].observaciones

def test_conciliacion_con_y_sin_vencimiento():
    # Antes fallaba con NameError (faltaba "from datetime import date") al ordenar fechas None
    oc=[{'sku':'A','lote':'L','unidades':10}]
    pl=[{'sku':'A','lote':'L','fecha_vencimiento':'2028-01-01','unidades':10}]
    r=conciliar(oc,pl,[])
    assert len(r)==2 and r[0].fecha_vencimiento is None
