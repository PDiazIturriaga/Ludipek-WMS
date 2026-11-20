-- =====================================================================
-- LUDIPEK WMS · 37 FARMACIA: UBICACIÓN ÚNICA, MESA DE FARMACIA Y SIN PACKING  (requiere 11, 12 y 19)
--
-- · Ubicación FARMACIA (Bodega Santiago): una sola zona donde están todos los productos de
--   farmacia (todavía no hay ubicaciones unitarias). Cuenta como ubicación de PICKING: el picking
--   la sugiere primero, el stock se descuenta de ahí y "Movimiento a picking" puede reponerla
--   desde la reserva. Para que el picking la proponga siempre, se puede fijar como ubicación de
--   picking de cada SKU de farmacia (al final del script).
-- · Mesa de farmacia ("MESA FARMACIA"): donde queda el pedido de farmacia ya pickeado.
-- · Pedidos de farmacia (-FA) sin packing: al cerrar el picking pasan directo a
--   PENDIENTE_FACTURACION (1 bulto). Se generan igual el packing list, los datos de despacho y la
--   entrada a ruteo, como si se hubiera cerrado el packing. Las OT de traslado (OT-...) siguen
--   pasando por packing (van en pallets con LPN).
-- =====================================================================
begin;

-- ---------------------------------------------------------------------
-- 1. Ubicación FARMACIA
-- ---------------------------------------------------------------------
insert into public.bodega_ubicaciones (codigo_ubicacion, zona, pasillo, rack, nivel, posicion, tipo_almacenamiento,
                                       tipo_ubicacion, estado, estado_ubicacion, bodega)
values ('FARMACIA', 'FARMACIA', null, null, null, null, 'ESTANTERIA', 'ZONA_ESPECIAL', 'Habilitada', 'DISPONIBLE',
        'Bodega Santiago')
on conflict (bodega, codigo_ubicacion) do update
  set zona = excluded.zona, tipo_ubicacion = excluded.tipo_ubicacion, estado = 'Habilitada', estado_ubicacion = 'DISPONIBLE';

-- FARMACIA es ubicación de picking (igual que el nivel 01 de los racks)
create or replace function public.wms_es_ubicacion_picking(p text)
returns boolean language sql immutable as $$
  select upper(btrim(coalesce(p, ''))) ~ '^[A-Z]-[0-9]{2}-01$' or upper(btrim(coalesce(p, ''))) = 'FARMACIA';
$$;

-- Almacenamiento dirigido: un SKU con picking fijo en FARMACIA se sugiere guardar en FARMACIA
create or replace function public.wms_sugerir_ubicacion_lpn(p_bodega text, p_lpn text)
returns table (ubicacion text, motivo text, prioridad integer)
language plpgsql stable security definer set search_path = public as $$
#variable_conflict use_column
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_lpn text := upper(btrim(coalesce(p_lpn, '')));
  v_sku text;
  v_fija text;
  v_letra text;
  v_col int;
begin
  -- SKU principal del pallet (andén o rack)
  select x.sku into v_sku from (
    select r.sku, sum(r.unidades_totales) un from registro_recepcion r
     where r.bodega = v_bodega and upper(r.lpn) = v_lpn group by r.sku
    union all
    select i.sku, sum(i.cantidad_unidades) from bodega_inventario_ubicacion i
     where i.bodega = v_bodega and upper(i.lpn) = v_lpn and i.cantidad_unidades > 0 group by i.sku
  ) x order by x.un desc limit 1;
  if v_sku is null then return; end if;
  v_fija := public.wms_picking_fijo_sku(v_bodega, v_sku);
  -- Producto de farmacia: todo va a la zona FARMACIA (no tiene rack ni columna)
  if v_fija = 'FARMACIA' then
    ubicacion := 'FARMACIA'; motivo := 'Producto de farmacia: va a la zona FARMACIA'; prioridad := 1;
    return next;
    return;
  end if;

  if v_fija is null then
    -- Sin picking asignado: cerca de donde ya está ese SKU en reserva
    select split_part(i.codigo_ubicacion, '-', 1), split_part(i.codigo_ubicacion, '-', 2)::int into v_letra, v_col
      from bodega_inventario_ubicacion i
     where i.bodega = v_bodega and i.sku = v_sku and i.codigo_ubicacion ~ '^[A-Z]-[0-9]{2}-[0-9]{2}$'
     group by 1, 2 order by sum(i.cantidad_unidades) desc limit 1;
    if v_letra is null then return; end if;
  else
    v_letra := split_part(v_fija, '-', 1);
    v_col := split_part(v_fija, '-', 2)::int;
    -- Picking vacío: el pallet puede quedar directo en su picking
    if not exists (select 1 from bodega_inventario_ubicacion i where i.bodega = v_bodega and i.codigo_ubicacion = v_fija
                     and i.cantidad_unidades > 0) then
      ubicacion := v_fija; motivo := 'Su picking (' || v_fija || ') está vacío: déjelo directo en picking'; prioridad := 1;
      return next;
    end if;
  end if;

  return query
  select u.codigo_ubicacion::text,
         case when split_part(u.codigo_ubicacion, '-', 2)::int = v_col
              then 'Reserva sobre su picking ' || coalesce(v_fija, v_letra || '-' || lpad(v_col::text, 2, '0'))
              else 'Reserva cercana (columna ' || split_part(u.codigo_ubicacion, '-', 2) || ')' end,
         (2 + abs(split_part(u.codigo_ubicacion, '-', 2)::int - v_col))::int
  from bodega_ubicaciones u
  where u.bodega = v_bodega
    and upper(u.codigo_ubicacion) ~ ('^' || v_letra || '-[0-9]{2}-[0-9]{2}$')
    and not public.wms_es_ubicacion_picking(u.codigo_ubicacion)
    and abs(split_part(u.codigo_ubicacion, '-', 2)::int - v_col) <= 3
    and coalesce(u.estado, '') not ilike 'bloque%' and coalesce(u.estado_ubicacion, '') not ilike 'bloque%'
    and coalesce(u.estado, '') not ilike 'deshabilit%'
    and not exists (select 1 from bodega_inventario_ubicacion i
                     where i.bodega = v_bodega and i.codigo_ubicacion = u.codigo_ubicacion and i.cantidad_unidades > 0)
  order by abs(split_part(u.codigo_ubicacion, '-', 2)::int - v_col), u.codigo_ubicacion
  limit 5;
end $$;

-- ---------------------------------------------------------------------
-- 2. Mesa de farmacia
-- ---------------------------------------------------------------------
create or replace function public.wms_normalizar_mesa(p text)
returns text language plpgsql immutable as $$
declare
  v_num text;
begin
  if upper(coalesce(p, '')) like '%FARMA%' then
    return 'MESA FARMACIA';
  end if;
  v_num := substring(upper(coalesce(p, '')) from '(\d{1,2})');
  if v_num is null then return null; end if;
  if v_num::int < 1 or v_num::int > 20 then
    raise exception 'WMS: mesa de packing inválida (%)', p;
  end if;
  return 'MESA ' || v_num::int;
end $$;

alter table public.netsuite_ordenes_venta drop constraint if exists ck_ov_mesa_packing;
alter table public.netsuite_ordenes_venta add constraint ck_ov_mesa_packing
  check (mesa_packing is null or mesa_packing ~ '^MESA ([1-9][0-9]?|FARMACIA)$');

-- ---------------------------------------------------------------------
-- 3. Cerrar picking de farmacia directo a facturación
-- ---------------------------------------------------------------------
create or replace function public.wms_es_pedido_farmacia(p_numero text)
returns boolean language sql immutable as $$
  select upper(coalesce(p_numero, '')) like '%-FA' and upper(coalesce(p_numero, '')) not like 'OT-%';
$$;

create or replace function public.wms_cerrar_picking_farmacia(p_orden_id bigint, p_lineas jsonb, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o record;
  d record;
  m record;
  v_detalle jsonb := '[]'::jsonb;
  v_suma int;
  v_peso numeric := 0;
  v_res jsonb;
begin
  select * into o from netsuite_ordenes_venta where id = p_orden_id;
  if not found then
    raise exception 'WMS: la orden % no existe', p_orden_id;
  end if;
  if not public.wms_es_pedido_farmacia(o.numero_ov) then
    raise exception 'WMS: la orden % no es de farmacia (-FA); debe pasar por packing', o.numero_ov;
  end if;

  -- a) Guardar lo pickeado (misma validación de siempre) y dejarla en la mesa de farmacia
  perform public.wms_cerrar_picking(p_orden_id, p_lineas, p_usuario, null);
  update netsuite_ordenes_venta
     set mesa_packing = 'MESA FARMACIA', mesa_asignada_en = now(),
         mesa_asignada_por = coalesce(nullif(upper(btrim(p_usuario)), ''), 'APP')
   where id = p_orden_id;

  -- b) Armar el "packing" automático con lo pickeado, lote por lote
  for d in select * from netsuite_detalle_ov where orden_id = p_orden_id and coalesce(cantidad_pickeada, 0) > 0 order by id loop
    v_suma := 0;
    for m in
      select btrim(split_part(x[1], ' / ', 1)) lote, btrim(split_part(x[1], ' / ', 2)) venc, x[2]::int un
        from regexp_matches(coalesce(d.lotes_pickeados, ''), '\s*([^|]+?)\s*\((\d+) UN\)', 'g') x
    loop
      v_detalle := v_detalle || jsonb_build_object('id_detalle', d.id, 'sku', d.sku, 'lote', coalesce(nullif(m.lote, ''), 'S/L'),
                                                   'fecha_vencimiento_cl', nullif(m.venc, ''), 'unidades_totales', m.un);
      v_suma := v_suma + m.un;
    end loop;
    if v_suma <> d.cantidad_pickeada then
      -- lotes sin detalle legible: una sola línea con el total (se conserva el texto original de lotes)
      v_detalle := (select coalesce(jsonb_agg(e), '[]'::jsonb) from jsonb_array_elements(v_detalle) e
                     where (e->>'id_detalle')::bigint <> d.id)
                   || jsonb_build_object('id_detalle', d.id, 'sku', d.sku,
                                         'lote', coalesce(nullif(split_part(coalesce(d.lotes_pickeados, ''), ' / ', 1), ''), 'S/L'),
                                         'unidades_totales', d.cantidad_pickeada);
    end if;
    select v_peso + d.cantidad_pickeada * coalesce(ms.peso_kg, ms.peso_gr / 1000.0, 0) into v_peso
      from maestra_sku ms where upper(ms.sku) = upper(public.wms_normalizar_sku(d.sku)) limit 1;
  end loop;

  -- c) Cierre igual que un packing de 1 bulto: packing list, despacho, ruteo y PENDIENTE_FACTURACION
  v_res := public.wms_cerrar_packing(p_orden_id, 'BULTOS', v_detalle, 1, 'BULTOS', null, null,
                                     nullif(round(v_peso, 2), 0), null, null,
                                     coalesce(nullif(upper(btrim(p_usuario)), ''), 'PICKING_FARMACIA'), null);
  return v_res || jsonb_build_object('mesa', 'MESA FARMACIA', 'sin_packing', true);
end $$;

grant execute on function public.wms_es_pedido_farmacia(text) to anon, authenticated, service_role;
grant execute on function public.wms_cerrar_picking_farmacia(bigint, jsonb, text) to anon, authenticated, service_role;

-- (Para usarlo, quite los dos guiones del inicio de cada línea de este bloque y ejecútelo aparte.)
-- ---------------------------------------------------------------------
-- 4. OPCIONAL · Pedidos de farmacia que ya estaban esperando packing: pasarlos a facturación
-- --    (solo los que no se empezaron a empacar)
-- ---------------------------------------------------------------------
-- do $$
-- declare
--   r record;
--   v_lineas jsonb;
-- begin
--   for r in select o.id from netsuite_ordenes_venta o
--             where public.wms_es_pedido_farmacia(o.numero_ov)
--               and upper(coalesce(o.estado_ns, '')) = 'PENDIENTE_PACKING' loop
--     select jsonb_agg(jsonb_build_object('id', d.id, 'cantidad_pickeada', coalesce(d.cantidad_pickeada, 0),
--                                         'lotes_pickeados', d.lotes_pickeados))
--       into v_lineas from netsuite_detalle_ov d where d.orden_id = r.id;
--     begin
--       perform public.wms_cerrar_picking_farmacia(r.id, v_lineas, 'SCRIPT_37');
--     exception when others then
--       raise notice 'Orden % no se pasó a facturación: %', r.id, sqlerrm;
--     end;
--   end loop;
-- end $$;

commit;

-- Revisión
select codigo_ubicacion, zona, tipo_ubicacion, bodega from public.bodega_ubicaciones where codigo_ubicacion = 'FARMACIA';
select numero_ov, estado_ns, mesa_packing from public.netsuite_ordenes_venta
 where public.wms_es_pedido_farmacia(numero_ov) order by id desc limit 10;

-- OPCIONAL · Fijar FARMACIA como ubicación de picking de todos los SKU que hoy tienen stock ahí
-- (después de mover el stock de farmacia a la ubicación FARMACIA):
-- insert into public.wms_ubicacion_picking_sku (bodega, sku, codigo_ubicacion)
-- select distinct 'Bodega Santiago', upper(sku), 'FARMACIA' from public.bodega_inventario_ubicacion
--  where bodega = 'Bodega Santiago' and codigo_ubicacion = 'FARMACIA' and cantidad_unidades > 0
-- on conflict do nothing;
