-- =====================================================================
-- LUDIPEK WMS · 19 UBICACIÓN DE PICKING FIJA POR SKU  (requiere 04, 15 y 16)
-- Cada SKU tiene su ubicación de picking (nivel 01). Con eso:
--   · El picking descuenta primero de esa ubicación y el celular la muestra en cada línea.
--   · La reposición a picking viene con esa ubicación ya puesta como destino.
--   · Almacenamiento dirigido: al escanear un LPN se sugiere dónde dejarlo
--     (sobre su picking: misma columna, niveles 02+; luego columnas cercanas).
-- Tabla propia (wms_ubicacion_picking_sku) para que una carga de la maestra
-- desde NetSuite no la borre; también se copia a maestra_sku.ubicacion_picking_fija.
-- Al final muestra cómo quedó cada asignación (OK / ubicación no existe / SKU no existe).
-- Para cambiar una asignación después:
--   select public.wms_asignar_picking_fijo('Bodega Santiago', 'USA603', 'H-03-01', 'PATRICIO');
-- =====================================================================

create table if not exists public.wms_ubicacion_picking_sku (
  bodega         text not null default 'Bodega Santiago',
  sku            text not null,
  ubicacion      text not null,
  actualizado_en timestamptz not null default now(),
  actualizado_por text,
  primary key (bodega, sku)
);
alter table public.wms_ubicacion_picking_sku enable row level security;
create index if not exists idx_picking_sku_ubicacion on public.wms_ubicacion_picking_sku (bodega, ubicacion);

create or replace function public.wms_picking_fijo_sku(p_bodega text, p_sku text)
returns text language sql stable security definer set search_path = public as $$
  select ubicacion from wms_ubicacion_picking_sku
   where bodega = public.wms_bodega_valida(p_bodega)
     and sku = regexp_replace(public.wms_normalizar_sku(p_sku), '-FA$', '');
$$;

create or replace function public.wms_picking_fijo_skus(p_bodega text, p_skus text[])
returns table (sku text, ubicacion text)
language sql stable security definer set search_path = public as $$
  select p.sku, p.ubicacion from wms_ubicacion_picking_sku p
   where p.bodega = public.wms_bodega_valida(p_bodega)
     and p.sku = any (select regexp_replace(public.wms_normalizar_sku(x), '-FA$', '') from unnest(p_skus) x);
$$;

create or replace function public.wms_asignar_picking_fijo(p_bodega text, p_sku text, p_ubicacion text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_sku text := regexp_replace(public.wms_normalizar_sku(p_sku), '-FA$', '');
  v_ubic text := public.wms_normalizar_ubicacion(p_ubicacion);
begin
  if v_ubic = '' then
    delete from wms_ubicacion_picking_sku where bodega = v_bodega and sku = v_sku;
    update maestra_sku set ubicacion_picking_fija = null where sku = v_sku;
    return jsonb_build_object('sku', v_sku, 'ubicacion', null);
  end if;
  if not public.wms_es_ubicacion_picking(v_ubic) then
    raise exception 'WMS: % no es una ubicación de picking (nivel 01)', v_ubic;
  end if;
  if not exists (select 1 from bodega_ubicaciones where bodega = v_bodega and upper(codigo_ubicacion) = v_ubic) then
    raise exception 'WMS: la ubicación % no existe en % ', v_ubic, v_bodega;
  end if;
  insert into wms_ubicacion_picking_sku (bodega, sku, ubicacion, actualizado_por)
  values (v_bodega, v_sku, v_ubic, upper(btrim(coalesce(p_usuario, 'SISTEMA'))))
  on conflict (bodega, sku) do update set ubicacion = excluded.ubicacion, actualizado_en = now(),
                                          actualizado_por = excluded.actualizado_por;
  update maestra_sku set ubicacion_picking_fija = v_ubic where sku = v_sku;
  return jsonb_build_object('sku', v_sku, 'ubicacion', v_ubic);
end $$;

-- ---------------------------------------------------------------------
-- Carga de la lista entregada por operaciones (19-11-2026)
-- ---------------------------------------------------------------------
create table if not exists public.wms_carga_picking_fijo (ubicacion text, sku text, estado text, cargado_en timestamptz default now());
truncate public.wms_carga_picking_fijo;
insert into public.wms_carga_picking_fijo (ubicacion, sku) values
  ('H-01-01', 'USA601'),
  ('H-02-01', 'USA602'),
  ('H-03-01', 'USA603'),
  ('H-04-01', 'USA604'),
  ('H-05-01', 'USA605'),
  ('H-06-01', 'USA606'),
  ('H-07-01', 'USA607'),
  ('H-08-01', 'USA608'),
  ('H-09-01', 'USA609'),
  ('H-10-01', 'USA611'),
  ('G-10-01', 'USA612'),
  ('G-09-01', 'USA615'),
  ('G-08-01', 'USA616'),
  ('G-07-01', 'USA621'),
  ('G-06-01', 'USA651'),
  ('G-05-01', 'USA652'),
  ('G-04-01', 'USA653'),
  ('G-03-01', 'USA661'),
  ('G-02-01', 'USA662'),
  ('G-01-01', 'USA663'),
  ('G-01-01', 'USA664'),
  ('F-01-01', 'USA665'),
  ('F-02-01', 'USA666'),
  ('F-03-01', 'USA667'),
  ('F-04-01', 'USA668'),
  ('F-05-01', 'USA669'),
  ('F-06-01', 'USA670'),
  ('F-06-01', 'USA677'),
  ('F-07-01', 'USA679'),
  ('F-08-01', 'USA680'),
  ('F-09-01', 'USA681'),
  ('F-10-01', 'USA682'),
  ('E-08-01', 'USA683'),
  ('E-07-01', 'USA691'),
  ('E-07-01', 'USA692'),
  ('E-06-01', 'USA693'),
  ('E-05-01', 'USA694'),
  ('E-05-01', 'USA695'),
  ('E-04-01', 'USA697'),
  ('E-03-01', 'USA701'),
  ('E-02-01', 'USA704'),
  ('E-01-01', 'USA711'),
  ('D-01-01', 'USA712'),
  ('D-02-01', 'USA721'),
  ('D-03-01', 'USA723'),
  ('D-04-01', 'USA741'),
  ('D-05-01', 'USA742'),
  ('D-06-01', 'USA743'),
  ('D-07-01', 'LAT657'),
  ('D-08-01', 'USD623'),
  ('D-08-01', 'USD622'),
  ('C-28-01', 'LDK650'),
  ('C-27-01', 'USA751'),
  ('C-26-01', 'USA752'),
  ('C-25-01', 'USA753'),
  ('C-24-01', 'USA754'),
  ('C-23-01', 'USA861'),
  ('C-22-01', 'USA863'),
  ('C-21-01', 'USA864'),
  ('C-20-01', 'USA868'),
  ('C-19-01', 'USA901'),
  ('C-18-01', 'USA903'),
  ('C-18-01', 'USA904'),
  ('C-17-01', 'USD601'),
  ('C-16-01', 'USD602'),
  ('C-15-01', 'USD603'),
  ('C-14-01', 'USD604'),
  ('C-13-01', 'USD605'),
  ('C-12-01', 'USD611'),
  ('C-11-01', 'USD612'),
  ('C-10-01', 'USD613'),
  ('C-09-01', 'USD614'),
  ('C-08-01', 'USD615'),
  ('C-07-01', 'USD721'),
  ('C-06-01', 'USD723'),
  ('C-05-01', 'USD741'),
  ('C-04-01', 'USD742'),
  ('C-03-01', 'USD743'),
  ('C-02-01', 'USD901'),
  ('C-02-01', 'USD902'),
  ('C-01-01', 'USD905');
-- LDK650 en la maestra figura como LKD650: se usa el que exista
update public.wms_carga_picking_fijo c set sku = 'LKD650'
 where c.sku = 'LDK650' and not exists (select 1 from maestra_sku where sku = 'LDK650')
   and exists (select 1 from maestra_sku where sku = 'LKD650');

update public.wms_carga_picking_fijo c set estado = case
    when not exists (select 1 from bodega_ubicaciones u where u.bodega = 'Bodega Santiago' and upper(u.codigo_ubicacion) = c.ubicacion)
      then 'NO CARGADA: la ubicación no existe en Bodega Santiago'
    when not exists (select 1 from maestra_sku m where m.sku = c.sku)
      then 'CARGADA (el SKU aún no está en la maestra)'
    when exists (select 1 from bodega_ubicaciones u where u.bodega = 'Bodega Santiago' and upper(u.codigo_ubicacion) = c.ubicacion
                  and (u.estado ilike 'bloque%' or u.estado_ubicacion ilike 'bloque%'))
      then 'CARGADA, PERO LA UBICACIÓN ESTÁ BLOQUEADA'
    else 'OK' end;

insert into public.wms_ubicacion_picking_sku (bodega, sku, ubicacion, actualizado_por)
select 'Bodega Santiago', c.sku, c.ubicacion, 'CARGA 19-11-2026'
from public.wms_carga_picking_fijo c where c.estado not like 'NO CARGADA%'
on conflict (bodega, sku) do update set ubicacion = excluded.ubicacion, actualizado_en = now(),
                                        actualizado_por = excluded.actualizado_por;

update public.maestra_sku m set ubicacion_picking_fija = p.ubicacion
  from public.wms_ubicacion_picking_sku p
 where p.bodega = 'Bodega Santiago' and p.sku = m.sku and m.ubicacion_picking_fija is distinct from p.ubicacion;

-- ---------------------------------------------------------------------
-- Almacenamiento dirigido: dónde dejar un LPN
-- ---------------------------------------------------------------------
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
-- Salida de picking: primero la ubicación de picking del SKU
-- ---------------------------------------------------------------------
create or replace function public.wms_salida_picking(
  p_bodega text, p_sku text, p_lote text, p_unidades integer, p_numero_ov text,
  p_usuario text default null, p_ubicacion text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_fija text;
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
  v_fija := public.wms_picking_fijo_sku(p_bodega, p_sku);
  if v_sku like '%-FA' then v_sku := left(v_sku, length(v_sku) - 3); end if;
  if v_pend <= 0 then
    raise exception 'WMS: la cantidad a descontar debe ser mayor a 0';
  end if;

  for r in
    select * from bodega_inventario_ubicacion
     where bodega = v_bodega and sku in (v_sku, v_sku || '-FA') and lote = v_lote
       and not public.wms_es_ubicacion_merma(codigo_ubicacion) and cantidad_unidades > 0
     order by case when v_ubic <> '' and codigo_ubicacion = v_ubic then 0
                   when codigo_ubicacion = v_fija then 1
                   when public.wms_es_ubicacion_picking(codigo_ubicacion) then 2
                   when codigo_ubicacion = 'ZONA-PICKING' then 3
                   when public.wms_es_ubicacion_arena(codigo_ubicacion) then 4 else 5 end,
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

grant execute on function public.wms_picking_fijo_sku(text, text) to anon, authenticated, service_role;
grant execute on function public.wms_picking_fijo_skus(text, text[]) to anon, authenticated, service_role;
grant execute on function public.wms_asignar_picking_fijo(text, text, text, text) to authenticated, service_role;
grant execute on function public.wms_sugerir_ubicacion_lpn(text, text) to anon, authenticated, service_role;
grant execute on function public.wms_salida_picking(text, text, text, integer, text, text, text) to anon, authenticated, service_role;

-- Resultado de la carga
select ubicacion, sku, estado from public.wms_carga_picking_fijo order by estado desc, ubicacion, sku;
