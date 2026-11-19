-- =====================================================================
-- LUDIPEK WMS · 14 CENTRO DE ALERTAS DE LA OPERACIÓN  (requiere 04, 09, 10, 11, 12 y 13)
-- Se puede volver a ejecutar sin riesgo (actualiza la función).
-- Una sola función revisa toda la bodega y devuelve lo que necesita acción,
-- con el documento exacto y el módulo donde se resuelve. El PC la muestra
-- en el portal ("Requiere atención").
--   · Las alertas de ESTADO (vencidos, andén sin ubicar, OT demoradas...)
--     desaparecen solas cuando se corrige la causa.
--   · Las alertas de EVENTO (faltante de packing, diferencia de traslado,
--     picking sin stock) se marcan como revisadas con una nota.
-- Solo lectura sobre la operación: no modifica stock ni órdenes.
-- =====================================================================
begin;

create table if not exists public.wms_alertas_revisadas (
  codigo       text not null,
  referencia   text not null,
  bodega       text,
  nota         text,
  revisado_por text not null,
  revisado_en  timestamptz not null default now(),
  primary key (codigo, referencia)
);
alter table public.wms_alertas_revisadas enable row level security;

create or replace function public.wms_alertas_operacion(p_bodega text)
returns table (codigo text, severidad text, titulo text, descripcion text, modulo text, revisable boolean,
               cantidad integer, items jsonb)
language plpgsql stable security definer set search_path = public as $$
#variable_conflict use_column
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_hoy date := (now() at time zone 'America/Santiago')::date;
begin
  -- 1) Packing cerrado con faltante (evento)
  return query
  with x as (
    select d.numero_ov ref, d.cerrado_en f,
           format('%s · %s: faltan %s UN (%s)', d.numero_ov, coalesce(d.cliente_nombre, '-'), d.faltante_un,
                  coalesce(d.motivo_faltante, 'sin motivo')) txt
    from wms_despacho_ov d
    where d.bodega = v_bodega and coalesce(d.faltante_un, 0) > 0 and d.cerrado_en > now() - interval '30 days'
      and not exists (select 1 from wms_alertas_revisadas r where r.codigo = 'PACKING_FALTANTE' and r.referencia = d.numero_ov)
  )
  select 'PACKING_FALTANTE', 'ALTA', 'Pedidos despachados con faltante',
         'Se cerró el packing con unidades de menos. Revise el stock de esos SKU (conteo) y avise al cliente.',
         'OLAS', true, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', ref, 'texto', txt, 'fecha', f) order by f desc), '[]')
  from x having count(*) > 0;

  -- 2) Traslados recibidos con diferencias o pallets que no llegaron (evento, ambas bodegas)
  return query
  with x as (
    select t.numero_ot || ' / ' || t.lpn ref, t.fecha_recepcion f,
           format('%s · pallet %s: %s (%s de %s UN)%s', t.numero_ot, t.lpn,
                  case t.estado when 'NO_LLEGO' then 'no llegó' else 'con diferencias' end,
                  t.total_unidades_recibidas, t.total_unidades_despachadas,
                  coalesce(' · ' || nullif(t.observacion, ''), '')) txt
    from wms_recepcion_traslados_ccp t
    where t.estado in ('RECIBIDO_CON_DIFERENCIAS', 'NO_LLEGO') and t.fecha_recepcion > now() - interval '30 days'
      and not exists (select 1 from wms_alertas_revisadas r
                      where r.codigo = 'TRASLADO_DIFERENCIA' and r.referencia = t.numero_ot || ' / ' || t.lpn)
  )
  select 'TRASLADO_DIFERENCIA', 'ALTA', 'Traslados a Concepción con diferencias',
         'Lo recibido en Concepción no cuadra con lo enviado desde Santiago.',
         'TRASLADOS', true, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', ref, 'texto', txt, 'fecha', f) order by f desc), '[]')
  from x having count(*) > 0;

  -- 3) Picking que descontó sin stock registrado (evento)
  return query
  with x as (
    select h.id::text ref, h.fecha f,
           format('%s · SKU %s lote %s: %s UN sin stock en sistema', substring(h.tipo_movimiento from '\((.*)\)'),
                  h.sku, coalesce(h.lote, 'S/L'), h.unidades_afectadas) txt
    from historial_movimientos h
    where h.bodega = v_bodega and h.tipo_movimiento like 'SALIDA_PICKING_SIN_STOCK%' and h.fecha > now() - interval '30 days'
      and not exists (select 1 from wms_alertas_revisadas r where r.codigo = 'PICKING_SIN_STOCK' and r.referencia = h.id::text)
  )
  select 'PICKING_SIN_STOCK', 'ALTA', 'Se pickeó producto que el sistema no tenía',
         'El stock del sistema está desfasado: cree un conteo por SKU para corregirlo.',
         'INVENTARIO_TAREAS', true, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', ref, 'texto', txt, 'fecha', f) order by f desc), '[]')
  from x having count(*) > 0;

  -- 4) Lotes vencidos con stock (estado)
  return query
  with x as (
    select i.sku, i.lote, coalesce(i.fecha_vencimiento, public.wms_fecha_desde_texto(i.fecha_vencimiento_cl)) v,
           sum(i.cantidad_unidades) un, string_agg(distinct i.codigo_ubicacion, ', ') ubics
    from bodega_inventario_ubicacion i
    where i.bodega = v_bodega and i.cantidad_unidades > 0 and coalesce(i.codigo_ubicacion, '') <> 'ZONA-MERMA'
    group by 1, 2, 3
  )
  select 'LOTES_VENCIDOS', 'ALTA', 'Stock vencido en bodega',
         'Estos lotes ya vencieron y siguen disponibles. Muévalos a merma o bloquéelos para que no se pickeen.',
         'INVENTARIO', false, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', sku || ' / ' || lote, 'fecha', v,
             'texto', format('%s lote %s · venció %s · %s UN en %s', sku, lote, to_char(v, 'DD-MM-YYYY'), un, ubics))
           order by v), '[]')
  from x where v < v_hoy having count(*) > 0;

  -- 5) Lotes que vencen en los próximos 30 días (estado)
  return query
  with x as (
    select i.sku, i.lote, coalesce(i.fecha_vencimiento, public.wms_fecha_desde_texto(i.fecha_vencimiento_cl)) v,
           sum(i.cantidad_unidades) un
    from bodega_inventario_ubicacion i
    where i.bodega = v_bodega and i.cantidad_unidades > 0 and coalesce(i.codigo_ubicacion, '') <> 'ZONA-MERMA'
    group by 1, 2, 3
  )
  select 'POR_VENCER', 'MEDIA', 'Lotes que vencen en 30 días',
         'Priorice estos lotes en picking (FEFO) o gestione su salida.',
         'INVENTARIO', false, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', sku || ' / ' || lote, 'fecha', v,
             'texto', format('%s lote %s · vence %s · %s UN', sku, lote, to_char(v, 'DD-MM-YYYY'), un)) order by v), '[]')
  from x where v >= v_hoy and v < v_hoy + 30 having count(*) > 0;

  -- 6) Pallets recibidos hace más de 24 h y aún en el andén (estado)
  return query
  with x as (
    select r.lpn, min(r.fecha_recepcion) f, sum(r.unidades_totales) un, count(distinct r.sku) skus,
           string_agg(distinct coalesce(r.contenedor, ''), ', ') cont
    from registro_recepcion r
    where r.bodega = v_bodega and coalesce(r.estado_pallet, '') not in ('ALMACENADO', 'CERRADO_SIN_UBICAR')
      and r.fecha_recepcion between now() - interval '30 days' and now() - interval '24 hours'
      and not exists (select 1 from bodega_inventario_ubicacion i where i.bodega = r.bodega and i.lpn = r.lpn)
      and not exists (select 1 from historial_movimientos h where h.bodega = r.bodega and h.lpn = r.lpn
                      and h.tipo_movimiento in ('ALMACENAMIENTO', 'ENVIO_MERMA'))
    group by r.lpn
  )
  select 'ANDEN_SIN_UBICAR', 'ALTA', 'Pallets en andén hace más de 24 h',
         'Se recibieron pero nadie los almacenó: no se pueden pickear y el stock no aparece en racks.',
         'ALMACENAMIENTO', false, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', lpn, 'fecha', f,
             'texto', format('%s · %s SKU · %s UN · %s', lpn, skus, un, nullif(cont, ''))) order by f), '[]')
  from x having count(*) > 0;

  -- 6b) Pedidos por pickear sin stock suficiente en picking (nivel 01) y con reserva para bajar (estado)
  return query
  with dem as (
    select regexp_replace(upper(btrim(d.sku)), '-FA$', '') sku,
           sum(greatest(coalesce(d.cantidad_pedida, 0) - coalesce(d.cantidad_pickeada, 0), 0)) un,
           count(distinct o.id) ovs
    from netsuite_detalle_ov d join netsuite_ordenes_venta o on o.id = d.orden_id
    where coalesce(o.bodega, 'Bodega Santiago') = v_bodega
      and upper(coalesce(o.estado_ns, '')) in ('PENDIENTE_PICKING', 'PICKING_EN_PROCESO', 'PENDIENTE')
    group by 1
  ), st as (
    select i.sku,
           sum(i.cantidad_unidades) filter (where i.codigo_ubicacion ~ '^[A-Z]-[0-9]{2}-01$') pick,
           sum(i.cantidad_unidades) filter (where i.codigo_ubicacion ~ '^[A-Z]-[0-9]{2}-[0-9]{2}$'
                                              and i.codigo_ubicacion !~ '-01$' and coalesce(i.lote, '') not like '%|QA:%') res
    from bodega_inventario_ubicacion i
    where i.bodega = v_bodega and i.cantidad_unidades > 0
    group by i.sku
  ), x as (
    select dem.sku, dem.un, dem.ovs, coalesce(st.pick, 0) pick, coalesce(st.res, 0) res
    from dem join st on st.sku = dem.sku
    where dem.un > 0 and coalesce(st.pick, 0) < dem.un and coalesce(st.res, 0) > 0
  )
  select 'REABASTECER_PICKING', 'ALTA', 'Bajar a picking: no alcanza para los pedidos',
         'El nivel 01 no tiene stock suficiente para las OV pendientes y hay reserva en altura.',
         'REABASTECIMIENTO', false, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', sku,
             'texto', format('%s · piden %s UN en %s OV · picking %s · reserva %s', sku, un, ovs, pick, res))
           order by (un - pick) desc), '[]')
  from x having count(*) > 0;

  -- 7) OT en camino a Concepción hace más de 3 días (estado, ambas bodegas)
  return query
  with x as (
    select o.numero_ov, coalesce(d.cerrado_en, o.updated_at) f, upper(coalesce(o.estado_ns, o.estado)) est
    from netsuite_ordenes_venta o left join wms_despacho_ov d on d.orden_id = o.id
    where upper(o.numero_ov) like 'OT-%'
      and upper(coalesce(o.estado_ns, o.estado)) in ('EN_TRANSITO_CCP', 'RECEPCION_CCP_EN_PROCESO')
      and coalesce(d.cerrado_en, o.updated_at) < now() - interval '3 days'
  )
  select 'TRASLADO_DEMORADO', 'MEDIA', 'Traslados sin terminar de recibir (más de 3 días)',
         'La OT salió de Santiago y Concepción no la ha cerrado.',
         'TRASLADOS', false, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', numero_ov, 'fecha', f,
             'texto', format('%s · salió %s · %s', numero_ov, to_char(f at time zone 'America/Santiago', 'DD-MM HH24:MI'),
                             case est when 'EN_TRANSITO_CCP' then 'en camino' else 'recibiéndose' end)) order by f), '[]')
  from x having count(*) > 0;

  -- 8) Pedidos esperando en una mesa de packing más de 4 horas (estado)
  return query
  with x as (
    select o.numero_ov, o.mesa_packing, o.mesa_asignada_en f, o.cliente_nombre
    from netsuite_ordenes_venta o
    where coalesce(o.bodega, 'Bodega Santiago') = v_bodega and o.mesa_packing is not null
      and upper(coalesce(o.estado_ns, '')) in ('PENDIENTE_PACKING', 'PACKING_EN_PROCESO')
      and o.mesa_asignada_en < now() - interval '4 hours'
  )
  select 'MESA_DEMORADA', 'MEDIA', 'Pedidos esperando packing más de 4 horas',
         'Están pickeados en una mesa y nadie los ha empacado.',
         'OLAS', false, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', numero_ov, 'fecha', f,
             'texto', format('%s · %s · desde %s · %s', numero_ov, mesa_packing,
                             to_char(f at time zone 'America/Santiago', 'DD-MM HH24:MI'), coalesce(cliente_nombre, '-'))) order by f), '[]')
  from x having count(*) > 0;

  -- 9) Picking empezado y detenido hace más de 4 horas (estado)
  return query
  with x as (
    select o.numero_ov, o.updated_at f, o.operador_asignado, o.cliente_nombre
    from netsuite_ordenes_venta o
    where coalesce(o.bodega, 'Bodega Santiago') = v_bodega
      and upper(coalesce(o.estado_ns, '')) = 'PICKING_EN_PROCESO' and o.updated_at < now() - interval '4 hours'
  )
  select 'PICKING_DETENIDO', 'MEDIA', 'Picking detenido (más de 4 horas)',
         'La orden quedó a medio pickear. Confirme con el operador o reasígnela.',
         'OLAS', false, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', numero_ov, 'fecha', f,
             'texto', format('%s · %s · %s', numero_ov, coalesce(nullif(operador_asignado, ''), 'sin operador'),
                             coalesce(cliente_nombre, '-'))) order by f), '[]')
  from x having count(*) > 0;

  -- 10) Empacado y sin facturar hace más de 24 horas (estado)
  return query
  with x as (
    select o.numero_ov, coalesce(d.cerrado_en, o.updated_at) f, o.cliente_nombre
    from netsuite_ordenes_venta o left join wms_despacho_ov d on d.orden_id = o.id
    where coalesce(o.bodega, 'Bodega Santiago') = v_bodega
      and upper(coalesce(o.estado_ns, '')) = 'PENDIENTE_FACTURACION'
      and coalesce(d.cerrado_en, o.updated_at) < now() - interval '24 hours'
  )
  select 'FACTURACION_PENDIENTE', 'MEDIA', 'Empacados sin facturar (más de 24 horas)',
         'El pedido está listo en andén de despacho y no tiene factura.',
         'RUTEO', false, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', numero_ov, 'fecha', f,
             'texto', format('%s · %s · empacado %s', numero_ov, coalesce(cliente_nombre, '-'),
                             to_char(f at time zone 'America/Santiago', 'DD-MM HH24:MI'))) order by f), '[]')
  from x having count(*) > 0;

  -- 11) Un mismo LPN en más de una ubicación (estado)
  return query
  with x as (
    select i.lpn, string_agg(distinct i.codigo_ubicacion, ', ') ubics, count(distinct i.codigo_ubicacion) n
    from bodega_inventario_ubicacion i
    where i.bodega = v_bodega and coalesce(i.lpn, '') <> '' and i.cantidad_unidades > 0
      and i.codigo_ubicacion not in ('ZONA-PICKING', 'ZONA-MERMA') and i.codigo_ubicacion !~ '^[A-Z]-[0-9]{2}-01$'
    group by i.lpn having count(distinct i.codigo_ubicacion) > 1
  )
  select 'LPN_DUPLICADO', 'MEDIA', 'Un mismo LPN en varias ubicaciones',
         'El sistema no sabe dónde está el pallet. Cuente esas ubicaciones.',
         'INVENTARIO_TAREAS', false, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', lpn, 'texto', format('%s en %s ubicaciones: %s', lpn, n, ubics)) order by lpn), '[]')
  from x having count(*) > 0;

  -- 12) Tareas de conteo abiertas hace más de 2 días (estado)
  return query
  with x as (
    select a.id, a.tipo, coalesce(a.pasillo, a.sku) obj, a.usuario, a.creada_en f
    from wms_asignaciones_pasillo a
    where a.bodega = v_bodega and a.estado in ('PENDIENTE', 'EN_PROCESO') and a.creada_en < now() - interval '2 days'
  )
  select 'CONTEO_ATRASADO', 'BAJA', 'Tareas de conteo atrasadas',
         'Asignadas hace más de 2 días y sin terminar.',
         'INVENTARIO_TAREAS', false, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', id::text, 'fecha', f,
             'texto', format('%s %s · %s · desde %s', tipo, obj, usuario, to_char(f at time zone 'America/Santiago', 'DD-MM'))) order by f), '[]')
  from x having count(*) > 0;

  -- 13) SKU con stock y sin peso en la maestra (estado): el packing no puede estimar el peso
  return query
  with x as (
    select m.sku, m.descripcion descr, sum(i.cantidad_unidades) un
    from maestra_sku m join bodega_inventario_ubicacion i on i.sku = m.sku and i.bodega = v_bodega and i.cantidad_unidades > 0
    where coalesce(m.peso_gr, 0) <= 0 and coalesce(m.peso_kg, 0) <= 0
    group by m.sku, m.descripcion
  )
  select 'SKU_SIN_PESO', 'BAJA', 'Productos con stock y sin peso en la maestra',
         'Sin peso el packing no puede validar los bultos ni Ruteo calcular la carga.',
         'MAESTRA', false, count(*)::int,
         coalesce(jsonb_agg(jsonb_build_object('ref', sku, 'texto', format('%s · %s', sku, coalesce(descr, '-'))) order by un desc), '[]')
  from x having count(*) > 0;
end $$;

-- ---------------------------------------------------------------------
-- Marcar alertas de evento como revisadas (con nota)
-- ---------------------------------------------------------------------
create or replace function public.wms_marcar_alerta_revisada(
  p_codigo text, p_referencias text[], p_usuario text, p_nota text default null, p_bodega text default null)
returns integer language plpgsql security definer set search_path = public as $$
declare
  v_cod text := upper(btrim(coalesce(p_codigo, '')));
  v_n int;
begin
  if v_cod not in ('PACKING_FALTANTE', 'TRASLADO_DIFERENCIA', 'PICKING_SIN_STOCK') then
    raise exception 'WMS: la alerta % se resuelve corrigiendo la causa, no se marca como revisada', v_cod;
  end if;
  if coalesce(array_length(p_referencias, 1), 0) = 0 then
    raise exception 'WMS: indique qué registros revisó';
  end if;
  if nullif(btrim(coalesce(p_usuario, '')), '') is null then
    raise exception 'WMS: falta el usuario que revisa';
  end if;
  insert into wms_alertas_revisadas (codigo, referencia, bodega, nota, revisado_por)
  select v_cod, r, p_bodega, nullif(btrim(coalesce(p_nota, '')), ''), upper(btrim(p_usuario))
  from unnest(p_referencias) r where btrim(coalesce(r, '')) <> ''
  on conflict (codigo, referencia) do update
    set nota = excluded.nota, revisado_por = excluded.revisado_por, revisado_en = now();
  get diagnostics v_n = row_count;
  return v_n;
end $$;

grant execute on function public.wms_alertas_operacion(text) to anon, authenticated, service_role;
grant execute on function public.wms_marcar_alerta_revisada(text, text[], text, text, text) to anon, authenticated, service_role;

commit;
