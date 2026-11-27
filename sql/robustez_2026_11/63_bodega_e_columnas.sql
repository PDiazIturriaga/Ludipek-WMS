-- =====================================================================
-- LUDIPEK WMS · 63 ARENA BODEGA E POR COLUMNAS  (requiere 15; igual que el 20 para Marketing)
-- Bodega E deja de ser 10 filas x 20 posiciones (200 ubicaciones de 2 pallets) y pasa a
-- columnas de piso, una ubicación por columna:
--      Sector 1: BE-01-01, BE-01-02 ... BE-01-10
--      Sector 2: BE-02-11, BE-02-12 ... BE-02-20
--    Cada columna = 10 pallets de fondo x 2 de alto = 20 pallets (capacidad total 400, igual que antes).
-- Las posiciones BE antiguas que no son columna se borran si están vacías; si todavía tienen
-- stock quedan "Bloqueada" (no reciben más) hasta que se vacíen.
-- Se puede ejecutar las veces que quiera.
-- ⚠ No vuelva a ejecutar el 15 después de este: recrearía las 200 posiciones antiguas.
-- =====================================================================
begin;

-- 1) Las 20 columnas
insert into public.bodega_ubicaciones (codigo_ubicacion, zona, pasillo, rack, nivel, posicion, tipo_almacenamiento,
                                       tipo_ubicacion, estado, estado_ubicacion, bodega, capacidad_pallets)
select format('BE-%s-%s', lpad(s::text, 2, '0'), lpad(c::text, 2, '0')), 'ARENA-BE', 'BE-' || lpad(s::text, 2, '0'),
       'SECTOR ' || s, 'PISO', lpad(c::text, 2, '0'), 'PISO', 'ARENA', 'Habilitada', 'DISPONIBLE', 'Bodega Santiago', 20
from (select case when c <= 10 then 1 else 2 end s, c from generate_series(1, 20) c) x
on conflict (bodega, codigo_ubicacion) do update
  set zona = excluded.zona, pasillo = excluded.pasillo, rack = excluded.rack, nivel = excluded.nivel,
      posicion = excluded.posicion, tipo_almacenamiento = excluded.tipo_almacenamiento,
      tipo_ubicacion = excluded.tipo_ubicacion, capacidad_pallets = excluded.capacidad_pallets,
      estado = 'Habilitada', estado_ubicacion = 'DISPONIBLE';

-- 2) Posiciones antiguas: borrar las vacías, bloquear las que tengan stock
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
    where b.bodega = 'Bodega Santiago' and upper(b.codigo_ubicacion) ~ '^BE-[0-9]{2}-[0-9]{2}$'
      and upper(b.codigo_ubicacion) not in (
            select format('BE-%s-%s', case when c <= 10 then '01' else '02' end, lpad(c::text, 2, '0'))
            from generate_series(1, 20) c)
  loop
    if not u.con_stock then
      begin
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
  raise notice 'BE antiguas: % borradas, % bloqueadas (tienen stock: muévalo a las columnas nuevas)', v_borradas, v_bloqueadas;
end $$;

commit;

-- Revisión: deben salir 20 columnas habilitadas de 20 pallets
select rack as sector, count(*) columnas, min(codigo_ubicacion) desde, max(codigo_ubicacion) hasta,
       sum(capacidad_pallets) capacidad, string_agg(distinct estado, ', ') estado
from public.bodega_ubicaciones
where bodega = 'Bodega Santiago' and codigo_ubicacion like 'BE-%'
group by rack order by rack;

-- FIN 63
