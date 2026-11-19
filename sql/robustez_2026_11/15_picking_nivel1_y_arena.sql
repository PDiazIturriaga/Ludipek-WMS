-- =====================================================================
-- LUDIPEK WMS · 15 PICKING = NIVEL 01 Y ZONAS DE ARENA  (requiere 04)
-- 1) Picking es el nivel 01 de los racks (A-01-01 ... H-10-01).
--    · Movimiento a picking: el origen nunca es un nivel 01 ni merma, y el
--      destino tiene que ser un nivel 01.
--    · La salida de picking descuenta primero del nivel 01, luego de la
--      antigua ZONA-PICKING, luego arena y al final reserva. Nunca de merma.
-- 2) Zonas de arena dentro de Bodega Santiago (posiciones de piso, 2 pallets
--    apilados por posición, sin lote ni vencimiento):
--    · Marketing (detrás de los pasillos H a E):
--        MK-01..05-01..08 = Zona 1 · MK-06..10-01..08 = Zona 2 · MK-11-01..09 = Zona 3
--        ME-01..05-01..08 = Mermas (no se pickea)
--    (los textos caben en las columnas varchar(10) de bodega_ubicaciones)
--    · Bodega E: BE-01..10-01..20 (posiciones 01-10 = Zona 1 · 11-20 = Zona 2)
--    Almacenamiento rechaza un tercer pallet en la misma posición.
-- 3) Consultar LPN: las cajas bajadas a picking no cuentan como otra ubicación del pallet.
-- 4) wms_mover_lpn_a_picking: baja el LPN COMPLETO (todos sus lotes/fechas) a picking.
-- =====================================================================
begin;

-- ---------------------------------------------------------------------
-- Clasificación de ubicaciones (una sola definición para todo el sistema)
-- ---------------------------------------------------------------------
create or replace function public.wms_es_ubicacion_picking(p text)
returns boolean language sql immutable as $$
  select upper(btrim(coalesce(p, ''))) ~ '^[A-Z]-[0-9]{2}-01$';
$$;
create or replace function public.wms_es_ubicacion_arena(p text)
returns boolean language sql immutable as $$
  select upper(btrim(coalesce(p, ''))) ~ '^(MK|ME|BE)-[0-9]{2}-[0-9]{2}$';
$$;
create or replace function public.wms_es_ubicacion_merma(p text)
returns boolean language sql immutable as $$
  select upper(btrim(coalesce(p, ''))) = 'ZONA-MERMA' or upper(btrim(coalesce(p, ''))) ~ '^ME-[0-9]{2}-[0-9]{2}$';
$$;
grant execute on function public.wms_es_ubicacion_picking(text) to anon, authenticated, service_role;
grant execute on function public.wms_es_ubicacion_arena(text) to anon, authenticated, service_role;
grant execute on function public.wms_es_ubicacion_merma(text) to anon, authenticated, service_role;

-- ---------------------------------------------------------------------
-- Ubicaciones de arena
-- ---------------------------------------------------------------------
alter table public.bodega_ubicaciones add column if not exists capacidad_pallets integer;

insert into public.bodega_ubicaciones (codigo_ubicacion, zona, pasillo, rack, nivel, posicion, tipo_almacenamiento,
                                       tipo_ubicacion, estado, estado_ubicacion, bodega, capacidad_pallets)
select cod, zona, pasillo, sector, 'PISO', lpad(p::text, 2, '0'), 'PISO', tipo, 'Habilitada', 'DISPONIBLE',
       'Bodega Santiago', 2
from (
  -- Marketing zonas 1 y 2: 10 filas x 8 posiciones
  select format('MK-%s-%s', lpad(f::text, 2, '0'), lpad(p::text, 2, '0')) cod, 'ARENA-MK' zona,
         'MK-' || lpad(f::text, 2, '0') pasillo, case when f <= 5 then 'ZONA 1' else 'ZONA 2' end sector, 'ARENA' tipo, p
  from generate_series(1, 10) f, generate_series(1, 8) p
  union all
  -- Marketing zona 3: fila 11 con 9 posiciones
  select format('MK-11-%s', lpad(p::text, 2, '0')), 'ARENA-MK', 'MK-11', 'ZONA 3', 'ARENA', p
  from generate_series(1, 9) p
  union all
  -- Marketing zona mermas: 5 filas x 8 posiciones
  select format('ME-%s-%s', lpad(f::text, 2, '0'), lpad(p::text, 2, '0')), 'ARENA-ME',
         'ME-' || lpad(f::text, 2, '0'), 'MERMAS', 'MERMA', p
  from generate_series(1, 5) f, generate_series(1, 8) p
  union all
  -- Bodega E: 10 filas x 20 posiciones
  select format('BE-%s-%s', lpad(f::text, 2, '0'), lpad(p::text, 2, '0')), 'ARENA-BE',
         'BE-' || lpad(f::text, 2, '0'), case when p <= 10 then 'ZONA 1' else 'ZONA 2' end, 'ARENA', p
  from generate_series(1, 10) f, generate_series(1, 20) p
) u
on conflict (bodega, codigo_ubicacion) do update
  set zona = excluded.zona, pasillo = excluded.pasillo, rack = excluded.rack, nivel = excluded.nivel,
      posicion = excluded.posicion, tipo_almacenamiento = excluded.tipo_almacenamiento,
      tipo_ubicacion = excluded.tipo_ubicacion, capacidad_pallets = excluded.capacidad_pallets;

-- ---------------------------------------------------------------------
-- Funciones de operación con las reglas nuevas
-- ---------------------------------------------------------------------
drop function if exists public.wms_mover_a_picking(bigint, integer, text, text);

create or replace function public.wms_almacenar_lpn(
  p_bodega text, p_lpn text, p_ubicacion_destino text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_usuario text := public.wms_contexto(p_usuario, 'wms_almacenar_lpn');
  v_info jsonb;
  v_lpn text;
  v_dest text;
  v_tipo text;
  v_origen text;
  r record;
  v_n int := 0;
  v_unid int := 0;
  v_cap int;
  v_ocup int;
begin
  v_lpn := upper(btrim(coalesce(p_lpn, '')));
  if v_lpn ~ '^\d{18}$' then v_lpn := 'SSCC-' || v_lpn; end if;
  perform pg_advisory_xact_lock(hashtext('LPN|' || v_lpn));

  v_dest := public.wms_ubicacion_valida(v_bodega, p_ubicacion_destino);
  v_tipo := case when public.wms_es_ubicacion_merma(v_dest) then 'ENVIO_MERMA' else 'ALMACENAMIENTO' end;

  -- Ubicaciones con capacidad (arena: 2 pallets apilados por posición)
  select capacidad_pallets into v_cap from bodega_ubicaciones where bodega = v_bodega and codigo_ubicacion = v_dest;
  if coalesce(v_cap, 0) > 0 then
    select count(distinct coalesce(nullif(lpn, ''), id::text)) into v_ocup
    from bodega_inventario_ubicacion
    where bodega = v_bodega and codigo_ubicacion = v_dest and cantidad_unidades > 0 and coalesce(lpn, '') <> v_lpn;
    if v_ocup >= v_cap then
      raise exception 'WMS: la ubicación % ya tiene % pallet(s) (máximo %). Use otra posición.', v_dest, v_ocup, v_cap;
    end if;
  end if;
  v_info := public.wms_consultar_lpn(v_bodega, v_lpn);

  if v_info->>'estado' = 'EN_RACK' then
    v_origen := v_info->>'origen';
    if v_origen = v_dest then
      raise exception 'WMS: el LPN % ya está en %', v_lpn, v_dest;
    end if;
    for r in select * from bodega_inventario_ubicacion
              where bodega = v_bodega and lpn = v_lpn and codigo_ubicacion = v_origen
              order by id for update loop
      delete from bodega_inventario_ubicacion where id = r.id;
      perform public.wms_sumar_en_ubicacion(v_bodega, v_dest, r.sku, r.lote, r.lpn, r.fecha_vencimiento_cl, r.cajas, r.cantidad_unidades);
      perform public.wms_kardex(v_bodega, v_tipo, v_lpn, r.sku, r.lote, v_origen, v_dest, r.cajas, r.cantidad_unidades);
      v_n := v_n + 1; v_unid := v_unid + r.cantidad_unidades;
    end loop;

  elsif v_info->>'estado' = 'EN_ANDEN' then
    v_origen := 'ANDEN_TRANSITO';
    for r in select * from registro_recepcion where bodega = v_bodega and lpn = v_lpn order by id for update loop
      perform public.wms_sumar_en_ubicacion(v_bodega, v_dest, r.sku, r.lote, v_lpn, r.fecha_vencimiento_cl, r.cajas, r.unidades_totales);
      perform public.wms_kardex(v_bodega, v_tipo, v_lpn, r.sku, r.lote, v_origen, v_dest, r.cajas, r.unidades_totales);
      v_n := v_n + 1; v_unid := v_unid + r.unidades_totales;
    end loop;
    update registro_recepcion set ubicacion_destino = v_dest, estado_pallet = 'ALMACENADO'
     where bodega = v_bodega and lpn = v_lpn;

  else
    raise exception 'WMS: %', coalesce(v_info->>'mensaje', 'el LPN no se puede almacenar');
  end if;

  return jsonb_build_object('lpn', v_lpn, 'origen', v_origen, 'destino', v_dest, 'lineas', v_n, 'unidades', v_unid, 'tipo', v_tipo);
end $$;

create or replace function public.wms_mover_a_picking(
  p_inventario_id bigint, p_cajas integer, p_destino text default null, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_usuario text := public.wms_contexto(p_usuario, 'wms_mover_a_picking');
  o record;
  v_dest text;
  v_mult int;
  v_cajas int;
  v_unid int;
begin
  select * into o from bodega_inventario_ubicacion where id = p_inventario_id for update;
  if not found then
    raise exception 'WMS: el stock seleccionado ya no existe (otro operador lo movió). Vuelva a buscar el SKU.';
  end if;
  if o.lote like '%|QA:%' then
    raise exception 'WMS: el lote % está bloqueado por calidad y no puede ir a picking', o.lote;
  end if;
  if public.wms_es_ubicacion_picking(o.codigo_ubicacion) then
    raise exception 'WMS: % ya es una ubicación de picking (nivel 01). Elija stock de reserva.', o.codigo_ubicacion;
  end if;
  if public.wms_es_ubicacion_merma(o.codigo_ubicacion) then
    raise exception 'WMS: % es merma; ese stock no puede ir a picking', o.codigo_ubicacion;
  end if;
  if nullif(btrim(coalesce(p_destino, '')), '') is null then
    raise exception 'WMS: indique la ubicación de picking de destino (termina en -01, ej. H-02-01)';
  end if;
  v_dest := public.wms_ubicacion_valida(o.bodega, p_destino);
  if not public.wms_es_ubicacion_picking(v_dest) then
    raise exception 'WMS: % no es una ubicación de picking. El picking es el nivel 01 de los racks (ej. H-02-01).', v_dest;
  end if;
  if v_dest = o.codigo_ubicacion then
    raise exception 'WMS: el destino debe ser distinto del origen (%)', o.codigo_ubicacion;
  end if;
  if coalesce(p_cajas, 0) <= 0 then
    raise exception 'WMS: indique cuántas cajas mover';
  end if;

  v_mult := case when coalesce(o.cajas, 0) > 0 then greatest(round(o.cantidad_unidades::numeric / o.cajas)::int, 1) else 1 end;
  if coalesce(o.cajas, 0) > 0 and p_cajas > o.cajas then
    raise exception 'WMS: solo hay % cajas en %', o.cajas, o.codigo_ubicacion;
  end if;
  v_cajas := least(p_cajas, greatest(coalesce(o.cajas, 0), p_cajas));
  v_unid  := case when coalesce(o.cajas, 0) > 0 and v_cajas >= o.cajas then o.cantidad_unidades
                  else least(v_cajas * v_mult, o.cantidad_unidades) end;

  if o.cantidad_unidades - v_unid <= 0 then
    delete from bodega_inventario_ubicacion where id = o.id;
  else
    update bodega_inventario_ubicacion
       set cantidad_unidades = cantidad_unidades - v_unid,
           cajas = greatest(coalesce(cajas, 0) - v_cajas, 0),
           auditor = v_usuario, fecha = now()::text
     where id = o.id;
  end if;
  perform public.wms_sumar_en_ubicacion(o.bodega, v_dest, o.sku, o.lote, o.lpn, o.fecha_vencimiento_cl, v_cajas, v_unid);
  perform public.wms_kardex(o.bodega, 'MOVIMIENTO_PICKING', o.lpn, o.sku, o.lote, o.codigo_ubicacion, v_dest, v_cajas, v_unid);

  return jsonb_build_object('origen', o.codigo_ubicacion, 'destino', v_dest, 'cajas', v_cajas, 'unidades', v_unid, 'sku', o.sku, 'lote', o.lote);
end $$;

create or replace function public.wms_salida_picking(
  p_bodega text, p_sku text, p_lote text, p_unidades integer, p_numero_ov text,
  p_usuario text default null, p_ubicacion text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_usuario text := public.wms_contexto(p_usuario, 'wms_salida_picking');
  v_sku text := public.wms_normalizar_sku(p_sku);
  v_lote text := split_part(public.wms_normalizar_lote(p_lote), '|QA:', 1);
  v_ubic text := public.wms_normalizar_ubicacion(p_ubicacion);
  v_ov text := upper(btrim(coalesce(p_numero_ov, 'S/OV')));
  v_pend int := coalesce(p_unidades, 0);
  v_tomar int;
  v_cajas_nuevas int;
  v_mult int;
  v_detalle jsonb := '[]'::jsonb;
  r record;
begin
  if v_sku like '%-FA' then v_sku := left(v_sku, length(v_sku) - 3); end if;
  if v_pend <= 0 then
    raise exception 'WMS: la cantidad a descontar debe ser mayor a 0';
  end if;

  for r in
    select * from bodega_inventario_ubicacion
     where bodega = v_bodega and sku in (v_sku, v_sku || '-FA') and lote = v_lote
       and not public.wms_es_ubicacion_merma(codigo_ubicacion) and cantidad_unidades > 0
     order by case when v_ubic <> '' and codigo_ubicacion = v_ubic then 0
                   when public.wms_es_ubicacion_picking(codigo_ubicacion) then 1
                   when codigo_ubicacion = 'ZONA-PICKING' then 2
                   when public.wms_es_ubicacion_arena(codigo_ubicacion) then 3 else 4 end,
              fecha_vencimiento nulls last, id
     for update
  loop
    exit when v_pend <= 0;
    v_tomar := least(v_pend, r.cantidad_unidades);
    if r.cantidad_unidades - v_tomar <= 0 then
      delete from bodega_inventario_ubicacion where id = r.id;
      v_cajas_nuevas := 0;
    else
      v_mult := case when coalesce(r.cajas, 0) > 0 then greatest(round(r.cantidad_unidades::numeric / r.cajas)::int, 1) else 1 end;
      v_cajas_nuevas := case when coalesce(r.cajas, 0) > 0 then (r.cantidad_unidades - v_tomar) / v_mult else 0 end;
      update bodega_inventario_ubicacion
         set cantidad_unidades = cantidad_unidades - v_tomar, cajas = v_cajas_nuevas,
             auditor = v_usuario, fecha = now()::text
       where id = r.id;
    end if;
    perform public.wms_kardex(v_bodega, 'SALIDA_PICKING (' || v_ov || ')', r.lpn, r.sku, r.lote, r.codigo_ubicacion,
                              'PACKING ' || v_ov, coalesce(r.cajas, 0) - v_cajas_nuevas, v_tomar);
    v_detalle := v_detalle || jsonb_build_object('ubicacion', r.codigo_ubicacion, 'lpn', r.lpn, 'unidades', v_tomar);
    v_pend := v_pend - v_tomar;
  end loop;

  if v_pend > 0 then
    perform public.wms_kardex(v_bodega, 'SALIDA_PICKING_SIN_STOCK (' || v_ov || ')', null, v_sku, v_lote, 'SIN_REGISTRO',
                              'PACKING ' || v_ov, 0, v_pend);
  end if;

  return jsonb_build_object('sku', v_sku, 'lote', v_lote, 'solicitado', p_unidades,
                            'descontado', p_unidades - v_pend, 'faltante', v_pend, 'detalle', v_detalle);
end $$;

create or replace function public.wms_consultar_lpn(p_bodega text, p_lpn text)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_lpn text := upper(btrim(coalesce(p_lpn, '')));
  v_ubics text[];
  v_otra text;
begin
  if v_lpn ~ '^\d{18}$' then v_lpn := 'SSCC-' || v_lpn; end if;

  -- Ubicación del pallet: la reserva manda. Las cajas que se bajaron a picking (nivel 01)
  -- conservan el LPN como referencia, pero no cuentan como "otra ubicación" del pallet.
  select array_agg(distinct codigo_ubicacion) into v_ubics
  from bodega_inventario_ubicacion
  where bodega = v_bodega and lpn = v_lpn and codigo_ubicacion <> 'ZONA-PICKING'
    and not public.wms_es_ubicacion_picking(codigo_ubicacion) and cantidad_unidades > 0;
  if coalesce(array_length(v_ubics, 1), 0) = 0 then
    select array_agg(distinct codigo_ubicacion) into v_ubics
    from bodega_inventario_ubicacion
    where bodega = v_bodega and lpn = v_lpn and public.wms_es_ubicacion_picking(codigo_ubicacion) and cantidad_unidades > 0;
  end if;

  if coalesce(array_length(v_ubics, 1), 0) > 1 then
    return jsonb_build_object('estado', 'VARIAS_UBICACIONES', 'lpn', v_lpn, 'ubicaciones', to_jsonb(v_ubics),
      'mensaje', format('El LPN %s figura en %s ubicaciones (%s). Haga conteo cíclico antes de moverlo.', v_lpn, array_length(v_ubics, 1), array_to_string(v_ubics, ', ')));
  elsif coalesce(array_length(v_ubics, 1), 0) = 1 then
    return jsonb_build_object('estado', 'EN_RACK', 'lpn', v_lpn, 'origen', v_ubics[1], 'lineas',
      (select jsonb_agg(jsonb_build_object('id', id, 'sku', sku, 'lote', lote, 'fecha_vencimiento_cl', fecha_vencimiento_cl,
                                           'cajas', cajas, 'unidades_totales', cantidad_unidades) order by id)
       from bodega_inventario_ubicacion
       where bodega = v_bodega and lpn = v_lpn and codigo_ubicacion = v_ubics[1] and cantidad_unidades > 0));
  end if;

  if exists (select 1 from bodega_inventario_ubicacion where bodega = v_bodega and lpn = v_lpn)
     or exists (select 1 from historial_movimientos where bodega = v_bodega and lpn = v_lpn
                and tipo_movimiento in ('ALMACENAMIENTO', 'ENVIO_MERMA')) then
    return jsonb_build_object('estado', 'SIN_SALDO', 'lpn', v_lpn,
      'mensaje', format('El LPN %s ya fue almacenado y no tiene saldo en rack (consumido o movido a picking).', v_lpn));
  end if;

  if exists (select 1 from registro_recepcion where bodega = v_bodega and lpn = v_lpn
             and coalesce(estado_pallet, '') = 'CERRADO_SIN_UBICAR') then
    return jsonb_build_object('estado', 'SIN_SALDO', 'lpn', v_lpn,
      'mensaje', format('La recepción del LPN %s fue cerrada sin ubicar (histórico). Si el pallet está físicamente en bodega, regístrelo con Conteo Cíclico.', v_lpn));
  end if;

  if exists (select 1 from registro_recepcion where bodega = v_bodega and lpn = v_lpn) then
    return jsonb_build_object('estado', 'EN_ANDEN', 'lpn', v_lpn, 'origen', 'ANDEN_TRANSITO', 'lineas',
      (select jsonb_agg(jsonb_build_object('id', id, 'sku', sku, 'lote', lote, 'fecha_vencimiento_cl', fecha_vencimiento_cl,
                                           'cajas', cajas, 'unidades_totales', unidades_totales) order by id)
       from registro_recepcion where bodega = v_bodega and lpn = v_lpn));
  end if;

  select bodega into v_otra from registro_recepcion where lpn = v_lpn limit 1;
  return jsonb_build_object('estado', 'NO_EXISTE', 'lpn', v_lpn, 'mensaje',
    case when v_otra is not null then format('El LPN %s pertenece a %s, no a %s.', v_lpn, v_otra, v_bodega)
         else format('El LPN %s no existe en recepción ni en inventario de %s.', v_lpn, v_bodega) end);
end $$;

-- ---------------------------------------------------------------------
-- Bajar a picking el LPN completo (todos sus lotes/vencimientos de esa ubicación)
-- ---------------------------------------------------------------------
create or replace function public.wms_mover_lpn_a_picking(
  p_inventario_id bigint, p_destino text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_usuario text := public.wms_contexto(p_usuario, 'wms_mover_lpn_a_picking');
  o record;
  r record;
  v_dest text;
  v_n int := 0;
  v_cajas int := 0;
  v_unid int := 0;
  v_lotes jsonb := '[]'::jsonb;
begin
  select * into o from bodega_inventario_ubicacion where id = p_inventario_id;
  if not found then
    raise exception 'WMS: el stock seleccionado ya no existe (otro operador lo movió). Vuelva a buscar el SKU.';
  end if;
  if coalesce(o.lpn, '') = '' then
    raise exception 'WMS: ese stock no tiene LPN; muévalo por cajas';
  end if;
  if public.wms_es_ubicacion_picking(o.codigo_ubicacion) then
    raise exception 'WMS: % ya es una ubicación de picking (nivel 01)', o.codigo_ubicacion;
  end if;
  if public.wms_es_ubicacion_merma(o.codigo_ubicacion) then
    raise exception 'WMS: % es merma; ese stock no puede ir a picking', o.codigo_ubicacion;
  end if;
  if nullif(btrim(coalesce(p_destino, '')), '') is null then
    raise exception 'WMS: indique la ubicación de picking de destino (termina en -01, ej. H-02-01)';
  end if;
  v_dest := public.wms_ubicacion_valida(o.bodega, p_destino);
  if not public.wms_es_ubicacion_picking(v_dest) then
    raise exception 'WMS: % no es una ubicación de picking. El picking es el nivel 01 de los racks (ej. H-02-01).', v_dest;
  end if;

  perform pg_advisory_xact_lock(hashtext('LPN|' || o.lpn));
  if exists (select 1 from bodega_inventario_ubicacion
             where bodega = o.bodega and lpn = o.lpn and codigo_ubicacion = o.codigo_ubicacion
               and cantidad_unidades > 0 and lote like '%|QA:%') then
    raise exception 'WMS: el LPN % tiene un lote bloqueado por calidad; no puede bajar completo a picking', o.lpn;
  end if;

  for r in select * from bodega_inventario_ubicacion
            where bodega = o.bodega and lpn = o.lpn and codigo_ubicacion = o.codigo_ubicacion and cantidad_unidades > 0
            order by fecha_vencimiento nulls last, id
            for update loop
    delete from bodega_inventario_ubicacion where id = r.id;
    perform public.wms_sumar_en_ubicacion(r.bodega, v_dest, r.sku, r.lote, r.lpn, r.fecha_vencimiento_cl,
                                          coalesce(r.cajas, 0), r.cantidad_unidades);
    perform public.wms_kardex(r.bodega, 'MOVIMIENTO_PICKING', r.lpn, r.sku, r.lote, r.codigo_ubicacion, v_dest,
                              coalesce(r.cajas, 0), r.cantidad_unidades);
    v_n := v_n + 1; v_cajas := v_cajas + coalesce(r.cajas, 0); v_unid := v_unid + r.cantidad_unidades;
    v_lotes := v_lotes || jsonb_build_object('sku', r.sku, 'lote', r.lote, 'vencimiento', r.fecha_vencimiento_cl,
                                             'cajas', r.cajas, 'unidades', r.cantidad_unidades);
  end loop;
  if v_n = 0 then
    raise exception 'WMS: el LPN % ya no tiene stock en %', o.lpn, o.codigo_ubicacion;
  end if;
  return jsonb_build_object('lpn', o.lpn, 'origen', o.codigo_ubicacion, 'destino', v_dest,
                            'lineas', v_n, 'cajas', v_cajas, 'unidades', v_unid, 'lotes', v_lotes);
end $$;


grant execute on function public.wms_mover_lpn_a_picking(bigint, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_consultar_lpn(text, text) to anon, authenticated, service_role;
grant execute on function public.wms_almacenar_lpn(text, text, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_mover_a_picking(bigint, integer, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_salida_picking(text, text, text, integer, text, text, text) to anon, authenticated, service_role;

commit;

-- Verificación: debe dar 89 · 40 · 200
-- select zona, count(*) from public.bodega_ubicaciones where zona like 'ARENA-%' group by zona order by zona;
