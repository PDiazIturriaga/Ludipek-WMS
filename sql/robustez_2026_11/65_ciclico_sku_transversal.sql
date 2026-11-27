-- =====================================================================
-- LUDIPEK WMS · 65 CONTEO CÍCLICO POR SKU TRANSVERSAL  (requiere 22)
-- El cíclico por SKU del celular mostraba solo el stock en ubicaciones (racks, picking,
-- arena, merma). Ahora muestra todo lo que está "hacia atrás" del despacho:
--   · UBICACIÓN : stock en racks, picking, arena y merma (como antes; se audita igual).
--   · ANDÉN     : pallets recibidos que aún no se almacenan (andén de recepción).
-- Lo que espera la carga del camión NO entra al cíclico: lo pickeado (ya salió de su
-- ubicación) y los LPN armados en un despacho EXP abierto o cerrado sin descuento.
-- wms_ciclico_sku_ubicaciones(bodega, sku) devuelve las filas listas para el celular.
-- auditoria_ciclico_sku guarda además el origen y la referencia (OC y contenedor del andén).
-- Se puede ejecutar las veces que quiera.
-- =====================================================================
begin;

alter table public.auditoria_ciclico_sku add column if not exists origen text;
alter table public.auditoria_ciclico_sku add column if not exists referencia text;

create or replace function public.wms_ciclico_sku_ubicaciones(p_bodega text, p_sku text)
returns jsonb
language sql stable security definer set search_path = public as $$
  with prm as (
    select public.wms_bodega_valida(p_bodega) bod, upper(btrim(coalesce(p_sku, ''))) sku
  ),
  en_exp as (     -- LPN armados en un despacho EXP que espera el camión: no se cuentan
    select distinct upper(btrim(l.lpn)) lpn
    from wms_despacho_lpn l join wms_despachos d on d.id = l.despacho_id, prm
    where d.bodega = prm.bod and d.estado in ('ABIERTO', 'CERRADO') and not coalesce(d.stock_descontado, false)
  ),
  ubic as (
    select i.id, 'UBICACION' origen,
           case when public.wms_es_ubicacion_picking(i.codigo_ubicacion) or i.codigo_ubicacion = 'ZONA-PICKING' then 'PICKING'
                when i.codigo_ubicacion = 'ZONA-MERMA' or i.codigo_ubicacion like 'ME-%' then 'MERMA'
                when i.codigo_ubicacion ~ '^(MK|BE)-' then 'ARENA'
                else 'RESERVA' end zona,
           i.codigo_ubicacion, upper(i.sku) sku, i.lpn, coalesce(i.lote, 'S/L') lote, i.fecha_vencimiento_cl,
           coalesce(i.cajas, 0) cajas, coalesce(i.cantidad_unidades, 0) unidades, null::text referencia
    from bodega_inventario_ubicacion i, prm
    where i.bodega = prm.bod and upper(i.sku) = prm.sku and coalesce(i.cantidad_unidades, 0) > 0
      and upper(btrim(coalesce(i.lpn, ''))) not in (select lpn from en_exp)
  ),
  anden as (
    select -min(r.id) id, 'ANDEN' origen, 'ANDEN' zona, 'ANDÉN RECEPCIÓN' codigo_ubicacion, prm.sku,
           upper(btrim(r.lpn)) lpn, coalesce(r.lote, 'S/L') lote, max(r.fecha_vencimiento_cl) fecha_vencimiento_cl,
           sum(coalesce(r.cajas, 0))::int cajas, sum(coalesce(r.unidades_totales, 0))::int unidades,
           left('OC ' || coalesce(max(r.documento_netsuite), 'S/OC') || ' · ' || coalesce(max(r.contenedor), 'SIN-CONTENEDOR')
                || ' · recibido ' || coalesce(max(r.fecha_recepcion_cl), ''), 120) referencia
    from registro_recepcion r, prm
    where r.bodega = prm.bod and upper(r.sku) = prm.sku
      and coalesce(btrim(r.lpn), '') <> '' and coalesce(r.unidades_totales, 0) > 0
      and upper(btrim(r.lpn)) not in (select lpn from en_exp)
      and coalesce(r.estado_pallet, '') not in ('ALMACENADO', 'CERRADO_SIN_UBICAR')
      and not exists (select 1 from bodega_inventario_ubicacion i where i.bodega = r.bodega and i.lpn = r.lpn)
      and not exists (select 1 from historial_movimientos h where h.bodega = r.bodega and h.lpn = r.lpn
                      and h.tipo_movimiento in ('ALMACENAMIENTO', 'ENVIO_MERMA'))
    group by prm.sku, upper(btrim(r.lpn)), coalesce(r.lote, 'S/L'), coalesce(r.fecha_vencimiento_cl, '')
  ),
  todo as (
    select * from ubic union all select * from anden
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'id', id, 'origen', origen, 'zona', zona, 'codigo_ubicacion', codigo_ubicacion, 'sku', sku,
           'lpn', lpn, 'lote', lote, 'fecha_vencimiento_cl', fecha_vencimiento_cl,
           'cajas', cajas, 'cantidad_unidades', unidades, 'referencia', referencia)
         order by case origen when 'UBICACION' then 1 else 2 end,
                  case zona when 'PICKING' then 1 when 'RESERVA' then 2 when 'ARENA' then 3 when 'MERMA' then 4 else 5 end,
                  codigo_ubicacion, lpn), '[]'::jsonb)
  from todo;
$$;
grant execute on function public.wms_ciclico_sku_ubicaciones(text, text) to anon, authenticated, service_role;

commit;

-- Revisión (cambie el SKU): cuántas filas y unidades hay por origen
-- select x->>'origen' origen, x->>'zona' zona, count(*) filas, sum((x->>'cantidad_unidades')::int) unidades
-- from jsonb_array_elements(public.wms_ciclico_sku_ubicaciones('Bodega Santiago', 'FEWTC136746')) x
-- group by 1, 2 order by 1, 2;

-- FIN 65
