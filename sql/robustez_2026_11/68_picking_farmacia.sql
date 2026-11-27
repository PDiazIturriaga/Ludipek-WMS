-- =====================================================================
-- LUDIPEK WMS · 68 PICKING FIJO EN "FARMACIA" PARA LOS SKU DE FARMACIA  (requiere 19 y 37)
-- El 37 creó la ubicación FARMACIA (cuenta como picking), pero no asignó los SKU: el bloque
-- opcional del final no se ejecutó (y además usaba una columna con otro nombre).
-- Este script fija FARMACIA como ubicación de picking de los SKU de farmacia. Con eso:
--   · el picking de pedidos -FA los busca en FARMACIA;
--   · Reabastecimiento y "Movimiento a picking" los bajan a FARMACIA (FEFO);
--   · almacenamiento sugiere FARMACIA cuando la zona está vacía.
-- Qué es un SKU de farmacia: el que aparece en pedidos -FA y al menos el 80% de sus líneas
-- de pedido son -FA (así un SKU que también se vende en otros canales no se mueve).
-- Paso 1 revisa · Paso 2 asigna · Paso 3 muestra dónde está hoy el stock para bajarlo.
-- Se puede ejecutar más de una vez. El stock NO se mueve solo: se baja con el celular.
-- =====================================================================

-- PASO 1 · Revisión: SKU candidatos (cambie 0.8 si quiere otro corte)
with lineas as (
  select upper(d.sku) sku,
         count(*) filter (where public.wms_es_pedido_farmacia(v.numero_ov)) lineas_fa,
         count(*) lineas_total
  from public.netsuite_detalle_ov d
  join public.netsuite_ordenes_venta v on v.id = d.orden_id
  where v.bodega = 'Bodega Santiago'
  group by 1
)
select l.sku, m.descripcion, m.marca, l.lineas_fa, l.lineas_total,
       round(100.0 * l.lineas_fa / l.lineas_total) as pct_fa,
       case when l.lineas_fa::numeric / l.lineas_total >= 0.8 then 'SE ASIGNA' else 'no (se vende en otros canales)' end as decision,
       p.ubicacion as picking_actual
from lineas l
left join public.maestra_sku m on upper(m.sku) = l.sku
left join public.wms_ubicacion_picking_sku p on p.bodega = 'Bodega Santiago' and upper(p.sku) = l.sku
where l.lineas_fa > 0
order by decision, l.sku;

-- PASO 2 · Asignar FARMACIA como picking fijo
begin;

do $$
declare
  v_nuevos int;
  v_cambiados int;
begin
  create temp table _sku_farmacia on commit drop as
  select upper(d.sku) sku
  from public.netsuite_detalle_ov d
  join public.netsuite_ordenes_venta v on v.id = d.orden_id
  where v.bodega = 'Bodega Santiago'
  group by 1
  having count(*) filter (where public.wms_es_pedido_farmacia(v.numero_ov)) > 0
     and count(*) filter (where public.wms_es_pedido_farmacia(v.numero_ov))::numeric / count(*) >= 0.8;

  select count(*) filter (where p.sku is null), count(*) filter (where p.sku is not null and p.ubicacion <> 'FARMACIA')
    into v_nuevos, v_cambiados
  from _sku_farmacia f
  left join public.wms_ubicacion_picking_sku p on p.bodega = 'Bodega Santiago' and upper(p.sku) = f.sku;

  insert into public.wms_ubicacion_picking_sku (bodega, sku, ubicacion, actualizado_en, actualizado_por)
  select 'Bodega Santiago', f.sku, 'FARMACIA', now(), 'SCRIPT_68' from _sku_farmacia f
  on conflict (bodega, sku) do update
    set ubicacion = 'FARMACIA', actualizado_en = now(), actualizado_por = 'SCRIPT_68'
    where public.wms_ubicacion_picking_sku.ubicacion is distinct from 'FARMACIA';

  raise notice 'SKU de farmacia con picking FARMACIA: % nuevos, % cambiados desde otra ubicación.', v_nuevos, v_cambiados;
end $$;

commit;

-- PASO 3 · Dónde está hoy el stock de esos SKU (lo que no está en FARMACIA hay que bajarlo)
select p.sku, m.descripcion,
       coalesce(sum(i.cantidad_unidades) filter (where i.codigo_ubicacion = 'FARMACIA'), 0) as un_en_farmacia,
       coalesce(sum(i.cantidad_unidades) filter (where i.codigo_ubicacion <> 'FARMACIA'), 0) as un_en_otras,
       string_agg(distinct i.codigo_ubicacion, ', ') filter (where i.codigo_ubicacion <> 'FARMACIA') as ubicaciones_actuales
from public.wms_ubicacion_picking_sku p
left join public.maestra_sku m on upper(m.sku) = upper(p.sku)
left join public.bodega_inventario_ubicacion i on i.bodega = p.bodega and upper(i.sku) = upper(p.sku) and i.cantidad_unidades > 0
where p.bodega = 'Bodega Santiago' and p.ubicacion = 'FARMACIA'
group by p.sku, m.descripcion
order by un_en_farmacia, p.sku;

-- FIN 68
