-- =====================================================================
-- LUDIPEK WMS · 64 RACK F: COLUMNAS 01 Y 02 SOLO TIENEN PICKING
-- En F-01 y F-02 no hay rack hacia arriba: solo existe el nivel 01 (picking).
-- Este script saca de la maestra las ubicaciones de reserva que no existen físicamente
-- (F-01-02, F-01-03 ... y F-02-02, F-02-03 ...):
--   · si están vacías se borran, junto con sus avisos "ocupada sin registro"
--     (ALERTA_VACIA_OCUPADA) de las auditorías de vacías;
--   · si el sistema todavía les tiene stock, quedan "Bloqueada" (no reciben más) y salen
--     en la revisión del final: ese stock hay que contarlo y moverlo a su ubicación real.
-- F-01-01 y F-02-01 (picking) no se tocan. Se puede ejecutar las veces que quiera.
-- =====================================================================
begin;

do $$
declare
  u record;
  v_borradas int := 0;
  v_bloqueadas int := 0;
begin
  for u in
    select b.id, b.bodega, b.codigo_ubicacion,
           exists (select 1 from public.bodega_inventario_ubicacion i
                    where i.bodega = b.bodega and upper(i.codigo_ubicacion) = upper(b.codigo_ubicacion)
                      and coalesce(i.cantidad_unidades, 0) > 0) con_stock
    from public.bodega_ubicaciones b
    where b.bodega = 'Bodega Santiago'
      and upper(btrim(b.codigo_ubicacion)) ~ '^F-0[12]-[0-9]{2}$'
      and upper(btrim(b.codigo_ubicacion)) !~ '-01$'
  loop
    if not u.con_stock then
      begin
        delete from public.historial_movimientos
         where tipo_movimiento = 'ALERTA_VACIA_OCUPADA' and upper(ubicacion_destino) = upper(u.codigo_ubicacion);
        delete from public.bodega_inventario_ubicacion
         where bodega = u.bodega and upper(codigo_ubicacion) = upper(u.codigo_ubicacion)
           and coalesce(cantidad_unidades, 0) <= 0;
        delete from public.bodega_ubicaciones where id = u.id;
        v_borradas := v_borradas + 1;
        continue;
      exception when others then
        null;   -- si algo la referencia, se bloquea abajo
      end;
    end if;
    update public.bodega_ubicaciones
       set estado = 'Bloqueada', estado_ubicacion = 'BLOQUEADA'
     where id = u.id;
    v_bloqueadas := v_bloqueadas + 1;
  end loop;
  raise notice 'Rack F col 01-02: % ubicaciones de reserva borradas, % bloqueadas (tienen stock)', v_borradas, v_bloqueadas;
end $$;

commit;

-- Revisión 1: debe quedar solo F-01-01 y F-02-01 habilitadas (más las bloqueadas con stock, si hay)
select codigo_ubicacion, estado
from public.bodega_ubicaciones
where bodega = 'Bodega Santiago' and upper(codigo_ubicacion) ~ '^F-0[12]-'
order by 1;

-- Revisión 2: stock que el sistema tiene en ubicaciones que no existen (contar y mover)
select i.codigo_ubicacion, i.lpn, i.sku, i.lote, i.cajas, i.cantidad_unidades
from public.bodega_inventario_ubicacion i
where i.bodega = 'Bodega Santiago' and upper(i.codigo_ubicacion) ~ '^F-0[12]-[0-9]{2}$'
  and upper(i.codigo_ubicacion) !~ '-01$' and coalesce(i.cantidad_unidades, 0) > 0
order by 1;

-- FIN 64
