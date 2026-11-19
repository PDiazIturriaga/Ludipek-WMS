-- =====================================================================
-- LUDIPEK WMS · 20 ARENA MARKETING POR COLUMNAS Y AVANCE DE TAREAS DE CONTEO  (requiere 09 y 15)
-- 1) Arena Marketing (MK) pasa a columnas de piso:
--      Sector 1: MK-01-01, MK-01-02 ... MK-01-05
--      Sector 2: MK-02-06, MK-02-07 ... MK-02-11
--    Cada columna = 8 pallets de fondo x 2 de alto = 16 pallets.
--    Las posiciones MK antiguas (MK-03-04, MK-11-09, ...) se borran si están vacías;
--    si todavía tienen stock quedan "Bloqueada" (no reciben más) hasta que se vacíen.
--    ME (mermas arena) y BE (Bodega E) no cambian.
-- 2) Tareas de conteo: el avance no subía después de contar porque
--    · el celular guarda la hora de Chile sin zona horaria y Supabase la leía como UTC
--      (el conteo quedaba "3 horas antes" de crear la tarea y no se contaba),
--    · las ubicaciones "sin revisar" de un reporte se contaban como hechas.
-- Todos los textos caben en las columnas varchar(10) de bodega_ubicaciones.
-- =====================================================================
begin;

-- ---------------------------------------------------------------------
-- 1) MK por columnas
-- ---------------------------------------------------------------------
insert into public.bodega_ubicaciones (codigo_ubicacion, zona, pasillo, rack, nivel, posicion, tipo_almacenamiento,
                                       tipo_ubicacion, estado, estado_ubicacion, bodega, capacidad_pallets)
select format('MK-%s-%s', lpad(s::text, 2, '0'), lpad(c::text, 2, '0')), 'ARENA-MK', 'MK-' || lpad(s::text, 2, '0'),
       'SECTOR ' || s, 'PISO', lpad(c::text, 2, '0'), 'PISO', 'ARENA', 'Habilitada', 'DISPONIBLE', 'Bodega Santiago', 16
from (select case when c <= 5 then 1 else 2 end s, c from generate_series(1, 11) c) x
on conflict (bodega, codigo_ubicacion) do update
  set zona = excluded.zona, pasillo = excluded.pasillo, rack = excluded.rack, nivel = excluded.nivel,
      posicion = excluded.posicion, tipo_almacenamiento = excluded.tipo_almacenamiento,
      tipo_ubicacion = excluded.tipo_ubicacion, capacidad_pallets = excluded.capacidad_pallets,
      estado = 'Habilitada', estado_ubicacion = 'DISPONIBLE';

do $$
declare
  u record;
  v_borradas int := 0;
  v_bloqueadas int := 0;
begin
  for u in
    select b.id, b.codigo_ubicacion,
           exists (select 1 from public.bodega_inventario_ubicacion i
                    where i.bodega = b.bodega and i.codigo_ubicacion = b.codigo_ubicacion
                      and coalesce(i.cantidad_unidades, 0) > 0) con_stock
    from public.bodega_ubicaciones b
    where b.bodega = 'Bodega Santiago' and upper(b.codigo_ubicacion) ~ '^MK-[0-9]{2}-[0-9]{2}$'
      and upper(b.codigo_ubicacion) not in (
            select format('MK-%s-%s', case when c <= 5 then '01' else '02' end, lpad(c::text, 2, '0'))
            from generate_series(1, 11) c)
  loop
    if not u.con_stock then
      begin
        -- filas en cero que aún apunten a la posición vieja
        delete from public.bodega_inventario_ubicacion
         where bodega = 'Bodega Santiago' and codigo_ubicacion = u.codigo_ubicacion and coalesce(cantidad_unidades, 0) <= 0;
        delete from public.bodega_ubicaciones where id = u.id;
        v_borradas := v_borradas + 1;
        continue;
      exception when others then
        null;   -- si algo la referencia, se bloquea abajo
      end;
    end if;
    update public.bodega_ubicaciones
       set estado = 'Bloqueada', estado_ubicacion = 'BLOQUEADA', capacidad_pallets = 2
     where id = u.id;
    v_bloqueadas := v_bloqueadas + 1;
  end loop;
  raise notice 'MK antiguas: % borradas, % bloqueadas (tienen stock: muévalo a las columnas nuevas)', v_borradas, v_bloqueadas;
end $$;

-- ---------------------------------------------------------------------
-- 2) Avance de tareas de conteo
-- ---------------------------------------------------------------------
-- Hora real de un registro del celular: si llegó sin zona horaria, Supabase lo guardó
-- como UTC; se toma la lectura más tardía entre ambas interpretaciones.
create or replace function public.wms_ts_app(p timestamptz)
returns timestamptz language sql stable as $$
  select greatest(p, (p at time zone 'UTC') at time zone 'America/Santiago');
$$;
grant execute on function public.wms_ts_app(timestamptz) to anon, authenticated, service_role;

create or replace function public.wms_tareas_conteo(
  p_bodega text, p_usuario text default null, p_solo_abiertas boolean default true)
returns table (id bigint, tipo text, pasillo text, sku text, descripcion text, usuario text, estado text,
               creada_en timestamptz, cerrada_en timestamptz, total integer, avance integer)
language sql stable security definer set search_path = public as $$
  with t as (
    select a.*, coalesce((select upper(btrim(w.nombre_completo)) from wms_usuarios w where upper(w.usuario) = a.usuario limit 1), a.usuario) as nombre
    from wms_asignaciones_pasillo a
    where a.bodega = public.wms_bodega_valida(p_bodega)
      and (p_usuario is null or a.usuario = upper(btrim(p_usuario)))
      and (not p_solo_abiertas or a.estado in ('PENDIENTE', 'EN_PROCESO')
           or a.cerrada_en > now() - interval '1 day')
  )
  select t.id::bigint, t.tipo, t.pasillo, t.sku,
         (select m.descripcion from maestra_sku m where upper(m.sku) = t.sku limit 1),
         t.usuario, t.estado, t.creada_en, t.cerrada_en,
         case t.tipo
           when 'PASILLO' then (select count(distinct i.codigo_ubicacion) from bodega_inventario_ubicacion i
                                where i.bodega = t.bodega and i.codigo_ubicacion like t.pasillo || '-%' and i.cantidad_unidades > 0)
           when 'VACIAS' then (select count(*) from bodega_ubicaciones u
                               where u.bodega = t.bodega and upper(u.codigo_ubicacion) like t.pasillo || '-%'
                                 and not exists (select 1 from bodega_inventario_ubicacion i
                                                 where i.bodega = u.bodega and i.codigo_ubicacion = upper(u.codigo_ubicacion)
                                                   and i.cantidad_unidades > 0))
           else (select count(distinct i.codigo_ubicacion) from bodega_inventario_ubicacion i
                 where i.bodega = t.bodega and i.sku = t.sku and i.cantidad_unidades > 0)
         end::int,
         case t.tipo
           when 'PASILLO' then (select count(distinct x.ub) from (
                                  select i.codigo_ubicacion ub from bodega_inventario_ubicacion i
                                   where i.bodega = t.bodega and i.codigo_ubicacion like t.pasillo || '-%'
                                     and upper(coalesce(i.auditor, '')) in (t.usuario, t.nombre)
                                     and public.wms_ts_app(public.wms_ts_seguro(i.fecha)) >= t.creada_en
                                  union
                                  select h.ubicacion_destino from historial_movimientos h
                                   where h.bodega = t.bodega and h.tipo_movimiento like 'AJUSTE_CICLICO%'
                                     and h.ubicacion_destino like t.pasillo || '-%'
                                     and upper(coalesce(h.usuario, '')) in (t.usuario, t.nombre) and h.fecha >= t.creada_en) x)
           when 'VACIAS' then (select count(distinct v.codigo_ubicacion) from auditoria_ubicaciones_vacias v
                               where coalesce(v.bodega, 'Bodega Santiago') = t.bodega
                                 and upper(v.codigo_ubicacion) like t.pasillo || '-%'
                                 and upper(coalesce(to_jsonb(v)->>'resultado_auditoria', to_jsonb(v)->>'estado', '')) <> 'SIN_REVISAR'
                                 and upper(coalesce(v.auditor, '')) in (t.usuario, t.nombre)
                                 and public.wms_ts_app(v.fecha) >= t.creada_en)
           else (select count(distinct c.codigo_ubicacion) from auditoria_ciclico_sku c
                 where coalesce(c.bodega, 'Bodega Santiago') = t.bodega and upper(c.sku) = t.sku
                   and upper(coalesce(c.auditor, '')) in (t.usuario, t.nombre)
                   and public.wms_ts_app(c.fecha) >= t.creada_en
                   and upper(coalesce(c.estado_auditoria, '')) not in ('PENDIENTE', 'SIN_REVISAR', ''))
         end::int
  from t
  order by case t.estado when 'EN_PROCESO' then 0 when 'PENDIENTE' then 1 else 2 end, t.creada_en desc;
$$;
grant execute on function public.wms_tareas_conteo(text, text, boolean) to anon, authenticated, service_role;

commit;

-- Revisión: columnas MK
select codigo_ubicacion, rack as sector, capacidad_pallets, estado
from public.bodega_ubicaciones
where bodega = 'Bodega Santiago' and codigo_ubicacion like 'MK-%'
order by codigo_ubicacion;
