-- =====================================================================
-- LUDIPEK WMS · 07b DIAGNÓSTICO DE UNA ORDEN (solo lectura)
-- Cambie el número en la línea "ov" y ejecute todo junto.
-- Caso: 133409-FA se pickeó en el celular pero no cambió de estado.
-- =====================================================================
with ov as (select '133409' as q)
select 'CABECERA' as que, o.id::text as id, o.numero_ov as documento,
       coalesce(o.estado_ns, '(vacío)') || ' / ' || coalesce(o.estado, '(vacío)') as estado,
       'bodega=' || coalesce(o.bodega, '(vacía)') ||
       case when o.bodega is not null and o.bodega not in ('Bodega Santiago', 'Bodega Concepcion')
            then '  <-- BODEGA MAL ESCRITA: la base rechazaba el cambio de estado' else '' end ||
       ' | operador=' || coalesce(o.operador_asignado, '-') || ' | canal=' || coalesce(o.canal_venta, '-') as detalle
from netsuite_ordenes_venta o, ov where o.numero_ov ilike '%' || ov.q || '%'
union all
select 'LÍNEA', d.id::text, d.sku,
       coalesce(d.estado_linea, '-'),
       'pedido=' || d.cantidad_pedida || ' pickeado=' || coalesce(d.cantidad_pickeada, 0) || ' lotes=' || coalesce(d.lotes_pickeados, '-')
from netsuite_detalle_ov d join netsuite_ordenes_venta o on o.id = d.orden_id, ov
where o.numero_ov ilike '%' || ov.q || '%'
union all
select 'KARDEX', h.id::text, h.sku, h.tipo_movimiento,
       h.unidades_afectadas || ' UN lote ' || coalesce(h.lote, '-') || ' desde ' || coalesce(h.ubicacion_origen, '-') || ' ' || h.fecha::text
from historial_movimientos h, ov where h.tipo_movimiento ilike '%' || ov.q || '%'
union all
select 'PACKING LIST', p.id::text, p.numero_ov, coalesce(p.usuario_picking, '-'), p.fecha_emision::text
from wms_packing_lists_fa p, ov where p.numero_ov ilike '%' || ov.q || '%'
union all
select 'HISTORIAL ESTADO', e.id::text, e.documento, e.estado_anterior || ' -> ' || e.estado_nuevo,
       e.usuario || ' ' || e.created_at::text || ' ' || coalesce(e.observacion, '')
from wms_historial_estados e, ov where e.documento ilike '%' || ov.q || '%'
order by 1, 2;
