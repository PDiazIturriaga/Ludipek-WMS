-- =====================================================================
-- LUDIPEK WMS · 56 PRODUCTOS QUE SE MANEJAN SOLO EN DISPLAY (sin caja)
--
-- Caso: FEWTK136708 estaba en la maestra como CAJA x6 y DISPLAY x6, pero no existe caja: son
-- displays de 6. Este script:
--   PASO 1 (solo lectura): muestra las filas de la maestra de los SKU de la lista.
--   PASO 2: deja esos SKU solo con UNIDAD y DISPLAY (la fila CAJA pasa a DISPLAY o se elimina si
--           ya hay un DISPLAY con el mismo código de barras).
--   PASO 3: el despacho de exportación y el resumen Excel cuentan displays (no cajas) cuando el
--           SKU no tiene fila CAJA.
-- Para otros SKU en la misma situación, agréguelos en las dos listas de abajo.
-- Se puede ejecutar más de una vez.
-- =====================================================================

-- PASO 1 · Revisión (no cambia nada)
select sku, codigo_barras, unidad_medida, multiplo, descripcion, activo
  from maestra_sku
 where upper(btrim(sku)) in ('FEWTK136708')            -- << lista de SKU
 order by sku, multiplo, unidad_medida;

-- PASO 2 · Corregir la maestra
begin;
with skus as (select unnest(array['FEWTK136708']) as sku),   -- << misma lista de SKU
cajas as (
  select m.ctid as fila, m.*
    from maestra_sku m join skus s on upper(btrim(m.sku)) = s.sku
   where upper(replace(coalesce(m.unidad_medida, ''), ' ', '_')) in ('CAJA', 'CAJA_MASTER', 'MASTER', 'CJ')
),
borradas as (     -- la CAJA sobra: ya existe un DISPLAY con el mismo código de barras
  delete from maestra_sku m using cajas c
   where m.ctid = c.fila
     and exists (select 1 from maestra_sku d
                  where upper(btrim(d.sku)) = upper(btrim(c.sku)) and d.codigo_barras = c.codigo_barras
                    and upper(coalesce(d.unidad_medida, '')) in ('DISPLAY', 'DSP'))
  returning m.sku
),
cambiadas as (    -- la CAJA pasa a DISPLAY (conserva su código de barras)
  update maestra_sku m set unidad_medida = 'DISPLAY'
    from cajas c
   where m.ctid = c.fila
     and not exists (select 1 from maestra_sku d
                      where upper(btrim(d.sku)) = upper(btrim(c.sku)) and d.codigo_barras = c.codigo_barras
                        and upper(coalesce(d.unidad_medida, '')) in ('DISPLAY', 'DSP'))
  returning m.sku
)
select (select count(*) from borradas) as cajas_eliminadas, (select count(*) from cambiadas) as cajas_pasadas_a_display;
commit;

-- PASO 3 · Empaque sin caja: se cuentan displays
begin;
create or replace function public.wms_empaque_sku(p_sku text)
returns table (multiplo_caja integer, multiplo_display integer, peso_unidad_kg numeric, descripcion text)
language sql stable security definer set search_path = public as $$
  with m as (
    select upper(replace(coalesce(unidad_medida, ''), ' ', '_')) um, multiplo, descripcion,
           coalesce(peso_kg, peso_gr / 1000.0) peso
      from maestra_sku where upper(btrim(sku)) = upper(btrim(p_sku)) and activo is distinct from false
  ),
  x as (
    select max(multiplo) filter (where um in ('CAJA', 'CAJA_MASTER', 'MASTER', 'CJ')) caja,
           max(multiplo) filter (where um in ('DISPLAY', 'DSP')) display,
           max(multiplo) mayor
      from m
  )
  select case when x.caja is not null then greatest(1, x.caja)
              when coalesce(x.display, 1) > 1 then 0          -- solo display: no hay caja
              else greatest(1, coalesce(x.mayor, 1)) end::int,
         greatest(1, coalesce(x.display, 1))::int,
         (select coalesce(max(peso) filter (where um in ('UN', 'UNIDAD', 'UNIT') and peso > 0),
                          max(peso / nullif(multiplo, 0)) filter (where um in ('CAJA', 'CAJA_MASTER', 'MASTER', 'CJ', 'DISPLAY', 'DSP') and peso > 0))
            from m),
         (select max(descripcion) filter (where nullif(btrim(descripcion), '') is not null and descripcion <> 'DESC') from m)
    from x;
$$;

-- unidades -> {cajas, displays, sueltas}; p_caja = 0 significa "solo display"
create or replace function public.wms_empaque_desglose(p_unidades integer, p_caja integer, p_display integer)
returns jsonb language sql immutable as $$
  select case
    when coalesce(p_caja, 0) <= 0 then jsonb_build_object(
      'cajas', 0,
      'displays', coalesce(p_unidades, 0) / greatest(1, coalesce(p_display, 1)),
      'sueltas', coalesce(p_unidades, 0) % greatest(1, coalesce(p_display, 1)))
    else jsonb_build_object(
      'cajas', coalesce(p_unidades, 0) / p_caja,
      'displays', case when coalesce(p_display, 1) > 1 and p_display < p_caja
                       then (coalesce(p_unidades, 0) % p_caja) / p_display else 0 end,
      'sueltas', case when coalesce(p_display, 1) > 1 and p_display < p_caja
                      then (coalesce(p_unidades, 0) % p_caja) % p_display
                      else coalesce(p_unidades, 0) % p_caja end)
  end;
$$;
commit;

-- Revisión final
select sku, codigo_barras, unidad_medida, multiplo from maestra_sku
 where upper(btrim(sku)) in ('FEWTK136708') order by multiplo, unidad_medida;
select * from public.wms_empaque_sku('FEWTK136708');
select public.wms_empaque_desglose(1950, (select multiplo_caja from public.wms_empaque_sku('FEWTK136708')),
                                   (select multiplo_display from public.wms_empaque_sku('FEWTK136708'))) as ejemplo_1950_un;
