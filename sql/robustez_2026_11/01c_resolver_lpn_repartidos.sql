-- =====================================================================
-- LUDIPEK WMS · 01c RESOLVER LPN REPARTIDOS EN DOS UBICACIONES
-- Ejecutar SOLO después de revisar físicamente cada ubicación.
-- Descomente el bloque que corresponda a lo que encontró en piso.
-- Ambas opciones quedan en el kardex y en wms_auditoria_inventario.
-- Reemplace 'PATRICIO' por su usuario.
-- =====================================================================

-- Situación al 18-11-2026 (exportación):
--  LPN-100742  TBHYPL01     S/L     42 cj/1260 un en D-21-02 (id 2185) y 42 cj/1260 un en D-22-02 (id 2186)
--              -> mismas cantidades, mismo operador (BETO), con 1 minuto de diferencia: probable DOBLE REGISTRO
--  LPN-100749  VPSA50701CL  26C20A  11 cj/528 un en D-23-02 (id 2308) y 2 cj/96 un en D-23-01 (id 2358)
--  LPN-100752  VPCY50809CL  59200    3 cj/864 un en D-23-02 (id 2314) y 2 cj/576 un en D-23-01 (id 2359)
--              -> cantidades distintas, mismo minuto (GABRIEL): probable pallet PARTIDO en dos niveles

-- ---------------------------------------------------------------------
-- OPCIÓN A · DOBLE REGISTRO: el pallet está solo en una ubicación.
-- Se deja en 0 la fila de la ubicación donde NO está (borra la fila y
-- registra AJUSTE_CICLICO_MODIFICACION por la diferencia).
-- Ejemplo: LPN-100742 está físicamente solo en D-22-02.
-- ---------------------------------------------------------------------
-- select wms_registrar_conteo('Bodega Santiago', 'D-21-02', 'TBHYPL01', 'S/L', null, 'LPN-100742', 0, 'FIJAR', 2185, 'PATRICIO');

-- ---------------------------------------------------------------------
-- OPCIÓN B · PALLET PARTIDO DE VERDAD: hay mercadería en ambas ubicaciones.
-- Imprima una etiqueta LPN nueva (módulo Etiquetas), péguela en la parte
-- de D-23-01 y asigne ese LPN a la fila correspondiente.
-- Ejemplo: parte de LPN-100749 en D-23-01 pasa a LPN-100749-B.
-- ---------------------------------------------------------------------
-- begin;
-- update public.bodega_inventario_ubicacion set lpn = 'LPN-100749-B' where id = 2358;
-- insert into public.historial_movimientos (bodega, usuario, tipo_movimiento, lpn, sku, lote, ubicacion_origen, ubicacion_destino, cajas_afectadas, unidades_afectadas)
-- select bodega, 'PATRICIO', 'REETIQUETADO (LPN-100749 -> LPN-100749-B)', lpn, sku, lote, codigo_ubicacion, codigo_ubicacion, cajas, cantidad_unidades
-- from public.bodega_inventario_ubicacion where id = 2358;
-- commit;

-- Mismo procedimiento para LPN-100752 (fila id 2359 en D-23-01):
-- begin;
-- update public.bodega_inventario_ubicacion set lpn = 'LPN-100752-B' where id = 2359;
-- insert into public.historial_movimientos (bodega, usuario, tipo_movimiento, lpn, sku, lote, ubicacion_origen, ubicacion_destino, cajas_afectadas, unidades_afectadas)
-- select bodega, 'PATRICIO', 'REETIQUETADO (LPN-100752 -> LPN-100752-B)', lpn, sku, lote, codigo_ubicacion, codigo_ubicacion, cajas, cantidad_unidades
-- from public.bodega_inventario_ubicacion where id = 2359;
-- commit;

-- ---------------------------------------------------------------------
-- Si las cantidades tampoco coinciden con lo contado, corrija la fila con
-- la cantidad real (FIJAR). Ojo: las unidades se calculan como
-- cajas x múltiplo de la maestra; verifique que el múltiplo sea el correcto.
-- ---------------------------------------------------------------------
-- select wms_registrar_conteo('Bodega Santiago', 'D-23-02', 'VPSA50701CL', '26C20A', null, 'LPN-100749', 11, 'FIJAR', 2308, 'PATRICIO');

-- Verificación final (debe quedar vacía):
select bodega, lpn, string_agg(distinct codigo_ubicacion, ', ') as ubicaciones, sum(cantidad_unidades) as unidades
from public.bodega_inventario_ubicacion
where lpn is not null and codigo_ubicacion not like 'ZONA-%'
group by bodega, lpn having count(distinct codigo_ubicacion) > 1;
