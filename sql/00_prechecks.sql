-- Solo diagnóstico. No modifica datos.
select numero_ov, count(*) cantidad, array_agg(id order by id) ids
from public.netsuite_ordenes_venta group by numero_ov having count(*) > 1;

select ubicacion_id, sku, lote, count(*) cantidad,
       array_agg(id order by id) ids,
       array_agg(distinct coalesce(fecha_vencimiento_cl,'S/F')) vencimientos,
       array_agg(distinct coalesce(lpn_origen,'S/LPN')) lpns
from public.bodega_inventario_ubicacion
where cantidad_unidades <> 0
group by ubicacion_id, sku, lote having count(*) > 1;

select orden_id, numero_ov, count(*) registros, max(id) ultimo_id
from public.wms_packing_lists_fa group by orden_id, numero_ov having count(*) > 1;

select estado, estado_ns, count(*)
from public.netsuite_ordenes_venta group by estado, estado_ns order by 3 desc;
