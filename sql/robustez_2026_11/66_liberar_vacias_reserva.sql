-- =====================================================================
-- LUDIPEK WMS · 66 LIBERAR "OCUPADAS PENDIENTES DE INVENTARIAR" EN RESERVA (nivel 02 hacia arriba)
-- En la auditoría de vacías, el doble toque deja la ubicación como "ocupada pendiente de
-- inventariar" (aviso ALERTA_VACIA_OCUPADA) y la saca del listado de vacías.
-- Este script borra esos avisos SOLO en ubicaciones de rack de nivel 02 hacia arriba
-- (A-05-02, C-12-04, ...), para que vuelvan al listado y se recuenten.
--   · Picking (nivel 01) NO se toca.
--   · Arena (MK / BE) y mermas (ME) NO se tocan.
--   · El historial de auditorías (auditoria_ubicaciones_vacias) se conserva.
-- Paso 1 es solo revisión. Paso 2 libera. Se puede ejecutar más de una vez.
-- =====================================================================

-- PASO 1 · Revisión: qué se va a liberar (ubicación y lo que anotó el auditor)
select h.ubicacion_destino as ubicacion,
       coalesce(nullif(h.lote, 'S/L'), h.sku) as detalle,
       h.usuario,
       to_char(h.fecha at time zone 'America/Santiago', 'DD-MM-YYYY HH24:MI') as marcada
from public.historial_movimientos h
where h.tipo_movimiento = 'ALERTA_VACIA_OCUPADA'
  and coalesce(h.bodega, 'Bodega Santiago') = 'Bodega Santiago'
  and upper(btrim(h.ubicacion_destino)) ~ '^[A-Z]-[0-9]{2}-[0-9]{2}$'
  and upper(btrim(h.ubicacion_destino)) !~ '-01$'
order by 1;

-- PASO 2 · Liberar
begin;

do $$
declare
  v_avisos int;
  v_ubic int;
begin
  select count(*), count(distinct upper(btrim(ubicacion_destino))) into v_avisos, v_ubic
  from public.historial_movimientos
  where tipo_movimiento = 'ALERTA_VACIA_OCUPADA'
    and coalesce(bodega, 'Bodega Santiago') = 'Bodega Santiago'
    and upper(btrim(ubicacion_destino)) ~ '^[A-Z]-[0-9]{2}-[0-9]{2}$'
    and upper(btrim(ubicacion_destino)) !~ '-01$';

  delete from public.historial_movimientos
  where tipo_movimiento = 'ALERTA_VACIA_OCUPADA'
    and coalesce(bodega, 'Bodega Santiago') = 'Bodega Santiago'
    and upper(btrim(ubicacion_destino)) ~ '^[A-Z]-[0-9]{2}-[0-9]{2}$'
    and upper(btrim(ubicacion_destino)) !~ '-01$';

  raise notice 'Liberadas % ubicaciones de reserva (% avisos borrados). Picking y arena sin cambios.', v_ubic, v_avisos;
end $$;

commit;

-- PASO 3 · Control: lo que queda marcado como ocupado (debe ser solo picking y arena)
select case when upper(btrim(ubicacion_destino)) ~ '^[A-Z]-[0-9]{2}-01$' then 'PICKING (se mantiene)'
            when upper(btrim(ubicacion_destino)) ~ '^(MK|BE|ME)-' then 'ARENA / MERMA (se mantiene)'
            else 'OTRA' end as tipo,
       count(distinct upper(btrim(ubicacion_destino))) as ubicaciones
from public.historial_movimientos
where tipo_movimiento = 'ALERTA_VACIA_OCUPADA'
  and coalesce(bodega, 'Bodega Santiago') = 'Bodega Santiago'
group by 1 order by 1;

-- FIN 66
