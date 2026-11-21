-- =====================================================================
-- LUDIPEK WMS · 41 ESTANTE GIWI (ubicación de picking provisoria)   (requiere 19, 37 y 38)
--
-- Mientras se cubican y sectorizan las ubicaciones, los productos Giwi se pickean desde un
-- estante: la ubicación ESTANTE-GIWI (Bodega Santiago).
-- · Cuenta como ubicación de picking: el celular la acepta como destino en "Movimiento a picking"
--   y el picking la muestra como ubicación del producto (va al final de la ruta).
-- · Los SKU Giwi quedan con ESTANTE-GIWI como ubicación de picking. Su ubicación anterior queda
--   guardada en wms_picking_fijo_respaldo para volver atrás (ver el final del script).
-- · El stock Giwi que hoy está en un picking de rack (por ejemplo A-05-01) aparece en
--   PC › Mov. Stock › Consolidar picking para moverlo al estante en un clic.
-- · Los pallets Giwi que llegan se sugieren a reserva (el pallet completo no cabe en el estante)
--   y se reponen por cajas al estante.
-- =====================================================================
begin;

-- 1. Ubicación
insert into public.bodega_ubicaciones (codigo_ubicacion, zona, pasillo, rack, nivel, posicion, tipo_almacenamiento,
                                       tipo_ubicacion, estado, estado_ubicacion, bodega)
values ('ESTANTE-GIWI', 'GIWI', null, null, null, null, 'ESTANTERIA', 'ZONA_ESPECIAL', 'Habilitada', 'DISPONIBLE',
        'Bodega Santiago')
on conflict (bodega, codigo_ubicacion) do update
  set zona = excluded.zona, tipo_ubicacion = excluded.tipo_ubicacion, estado = 'Habilitada', estado_ubicacion = 'DISPONIBLE';

-- 2. Es ubicación de picking (igual que el nivel 01 de los racks y FARMACIA)
create or replace function public.wms_es_ubicacion_picking(p text)
returns boolean language sql immutable as $$
  select upper(btrim(coalesce(p, ''))) ~ '^[A-Z]-[0-9]{2}-01$'
      or upper(btrim(coalesce(p, ''))) in ('FARMACIA', 'ESTANTE-GIWI');
$$;

-- Almacenamiento dirigido: un pallet Giwi no se sugiere al estante sino a reserva
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
  -- Zonas sin rack ni columna: farmacia y estante Giwi (script 41)
  if v_fija = 'FARMACIA' then
    ubicacion := 'FARMACIA'; motivo := 'Producto de farmacia: va a la zona FARMACIA'; prioridad := 1;
    return next;
    return;
  end if;
  if v_fija = 'ESTANTE-GIWI' then
    -- El pallet completo no cabe en el estante: se guarda en reserva y se repone por cajas.
    -- Sugerir reserva cerca de donde ya está ese SKU (como un SKU sin picking asignado).
    v_fija := null;
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

-- 3. Los SKU Giwi pasan a pickearse desde ESTANTE-GIWI (guardando su ubicación anterior)
create table if not exists public.wms_picking_fijo_respaldo (
  motivo     text not null,
  bodega     text not null,
  sku        text not null,
  ubicacion  text not null,
  guardado_en timestamptz not null default now(),
  primary key (motivo, bodega, sku)
);
alter table public.wms_picking_fijo_respaldo enable row level security;
revoke all on public.wms_picking_fijo_respaldo from anon, authenticated;
grant select, insert, update, delete on public.wms_picking_fijo_respaldo to service_role;

with giwi as (
  select distinct regexp_replace(upper(btrim(m.sku)), '-FA$', '') sku
    from public.maestra_sku m
   where upper(coalesce(m.marca, '') || ' ' || coalesce(m.descripcion, '')) ~ '(GIWI|GIGWI)'
      or upper(btrim(m.sku)) ~ '^(GIW|GIG)'
), respaldo as (
  insert into public.wms_picking_fijo_respaldo (motivo, bodega, sku, ubicacion)
  select 'ESTANTE-GIWI', f.bodega, f.sku, f.ubicacion
    from public.wms_ubicacion_picking_sku f join giwi g on g.sku = f.sku
   where f.bodega = 'Bodega Santiago' and f.ubicacion <> 'ESTANTE-GIWI'
  on conflict (motivo, bodega, sku) do nothing
  returning 1
)
insert into public.wms_ubicacion_picking_sku (bodega, sku, ubicacion, actualizado_en, actualizado_por)
select 'Bodega Santiago', g.sku, 'ESTANTE-GIWI', now(), 'SCRIPT 41'
  from giwi g
on conflict (bodega, sku) do update
  set ubicacion = 'ESTANTE-GIWI', actualizado_en = now(), actualizado_por = 'SCRIPT 41';

commit;

-- Revisión: SKU Giwi con su nueva ubicación de picking y dónde tienen stock hoy
select f.sku, f.ubicacion as picking_nuevo, r.ubicacion as picking_anterior,
       (select string_agg(i.codigo_ubicacion || ' (' || i.cantidad_unidades || ' UN)', ', ' order by i.codigo_ubicacion)
          from public.bodega_inventario_ubicacion i
         where i.bodega = f.bodega and upper(i.sku) = f.sku and i.cantidad_unidades > 0) as stock_hoy
  from public.wms_ubicacion_picking_sku f
  left join public.wms_picking_fijo_respaldo r on r.motivo = 'ESTANTE-GIWI' and r.bodega = f.bodega and r.sku = f.sku
 where f.bodega = 'Bodega Santiago' and f.ubicacion = 'ESTANTE-GIWI'
 order by f.sku;

-- =====================================================================
-- VOLVER ATRÁS (cuando estén cubicadas las ubicaciones definitivas). Ejecutar a mano:
-- update public.wms_ubicacion_picking_sku f set ubicacion = r.ubicacion, actualizado_en = now(), actualizado_por = 'REVERTIR 41'
--   from public.wms_picking_fijo_respaldo r
--  where r.motivo = 'ESTANTE-GIWI' and r.bodega = f.bodega and r.sku = f.sku and f.ubicacion = 'ESTANTE-GIWI';
-- delete from public.wms_ubicacion_picking_sku where bodega = 'Bodega Santiago' and ubicacion = 'ESTANTE-GIWI';
-- (los SKU Giwi que no tenían picking quedan sin asignar; asígnelos en PC › Maestra › Ubic. Picking)
-- =====================================================================
