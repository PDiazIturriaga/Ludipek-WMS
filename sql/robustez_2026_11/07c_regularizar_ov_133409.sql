-- =====================================================================
-- LUDIPEK WMS · 07c REGULARIZAR OV 133409-FA (requiere 04 y 07)
-- Lo que mostró el diagnóstico (18-11-2026):
--   · estado_ns = PENDIENTE_PACKING (el PC lo lee bien) pero la columna "estado"
--     quedó en PENDIENTE_PICKING -> por eso en Supabase parecía no cambiar.
--   · 25 líneas pickeadas (1 UN c/u) pero NINGÚN movimiento de kardex:
--     el celular que pickeó tenía la app antigua, que no descontaba stock.
-- PASO 1 (solo lectura): revisar el stock de cada lote pickeado.
-- PASO 2: descontar el stock y alinear el estado. Ejecutarlo UNA vez;
--         si se repite no descuenta de nuevo (revisa el kardex de la OV).
-- =====================================================================

-- PASO 1 ---------------------------------------------------------------
with lineas as (
  select d.id, upper(btrim(d.sku)) as sku,
         upper(btrim(split_part(d.lotes_pickeados, ' / ', 1))) as lote,
         d.cantidad_pickeada
  from netsuite_detalle_ov d
  join netsuite_ordenes_venta o on o.id = d.orden_id
  where o.numero_ov = '133409-FA' and coalesce(d.cantidad_pickeada, 0) > 0)
select l.sku, l.lote, l.cantidad_pickeada as pickeado,
       coalesce(sum(i.cantidad_unidades), 0) as stock_wms_lote,
       string_agg(i.codigo_ubicacion || ':' || i.cantidad_unidades, ', ') as ubicaciones,
       case when coalesce(sum(i.cantidad_unidades), 0) >= l.cantidad_pickeada then 'OK'
            else 'SIN STOCK EN WMS (quedará como SALIDA_PICKING_SIN_STOCK)' end as resultado_paso_2
from lineas l
left join bodega_inventario_ubicacion i
  on i.bodega = 'Bodega Santiago' and i.sku in (l.sku, l.sku || '-FA') and i.lote = l.lote
 and i.codigo_ubicacion <> 'ZONA-MERMA' and i.cantidad_unidades > 0
group by l.sku, l.lote, l.cantidad_pickeada
order by resultado_paso_2 desc, l.sku;

-- PASO 2 ---------------------------------------------------------------
begin;
do $$
declare
  o record;
  l record;
  n int := 0;
begin
  select * into o from netsuite_ordenes_venta where numero_ov = '133409-FA' for update;
  if not found then raise exception 'No existe la OV 133409-FA'; end if;

  if exists (select 1 from historial_movimientos where tipo_movimiento like 'SALIDA_PICKING%(133409-FA)') then
    raise notice 'El stock de 133409-FA ya estaba descontado: no se descuenta de nuevo.';
  else
    for l in
      select upper(btrim(d.sku)) as sku, upper(btrim(split_part(d.lotes_pickeados, ' / ', 1))) as lote, d.cantidad_pickeada
      from netsuite_detalle_ov d where d.orden_id = o.id and coalesce(d.cantidad_pickeada, 0) > 0
    loop
      perform public.wms_salida_picking(coalesce(o.bodega, 'Bodega Santiago'), l.sku, nullif(l.lote, ''),
                                        l.cantidad_pickeada, '133409-FA', 'REGULARIZACION', null);
      n := n + 1;
    end loop;
    raise notice 'Descontadas % líneas de 133409-FA', n;
  end if;

  -- Ambas columnas de estado iguales (el packing la pasará luego a PENDIENTE_FACTURACION)
  update netsuite_ordenes_venta set estado = estado_ns where id = o.id and estado is distinct from estado_ns;
end $$;
commit;

-- Verificación
select tipo_movimiento, sku, lote, ubicacion_origen, unidades_afectadas
from historial_movimientos where tipo_movimiento like 'SALIDA_PICKING%(133409-FA)' order by id;
