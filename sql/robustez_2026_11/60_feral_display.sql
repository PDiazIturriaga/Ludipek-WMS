-- =====================================================================================
-- 60 · Productos con ficha logística (59a): se manejan en DISPLAY, no en CAJA
--   Caso: los SKU Feral son tarros dentro de un cartón = DISPLAY (x6; sopas x12), no cajas.
--   Para cada SKU de wms_sku_logistica:
--     · la fila CAJA pasa a DISPLAY (o se elimina si ya hay un DISPLAY con el mismo código)
--     · queda un DISPLAY con el EAN del display de la ficha y su múltiplo (6 o 12)
--     · despachos y resúmenes cuentan displays (no cajas)
--   No cambia la fila UNIDAD ni el stock. Requiere 59a. Se puede ejecutar más de una vez.
--   Copie TODO el archivo (Ctrl+A). Debe terminar en "-- FIN 60".
-- =====================================================================================

-- PASO 1 · Cómo están hoy (solo lectura)
select m.sku, m.codigo_barras, m.unidad_medida, m.multiplo
  from maestra_sku m join wms_sku_logistica g on upper(btrim(m.sku)) = upper(g.sku)
 order by m.sku, m.multiplo, m.unidad_medida;

-- PASO 2 · CAJA -> DISPLAY con el EAN y el múltiplo de la ficha
do $$
declare
  g record;
  r record;
  v_n int;
  v_borradas int := 0;
  v_cambiadas int := 0;
  v_nuevas int := 0;
  v_avisos text := '';
begin
  for g in select * from wms_sku_logistica where coalesce(display_unidades, 0) > 1 loop
    -- a) CAJA que sobra: ya existe un DISPLAY con el mismo código de barras
    delete from maestra_sku m
     where upper(btrim(m.sku)) = upper(g.sku)
       and upper(replace(coalesce(m.unidad_medida, ''), ' ', '_')) in ('CAJA', 'CAJA_MASTER', 'MASTER', 'CJ')
       and exists (select 1 from maestra_sku d
                    where upper(btrim(d.sku)) = upper(g.sku) and d.codigo_barras = m.codigo_barras
                      and upper(coalesce(d.unidad_medida, '')) in ('DISPLAY', 'DSP'));
    get diagnostics v_n = row_count; v_borradas := v_borradas + v_n;
    -- b) el resto de las CAJA pasan a DISPLAY (conservan su código de barras)
    update maestra_sku m set unidad_medida = 'DISPLAY', multiplo = g.display_unidades
     where upper(btrim(m.sku)) = upper(g.sku)
       and upper(replace(coalesce(m.unidad_medida, ''), ' ', '_')) in ('CAJA', 'CAJA_MASTER', 'MASTER', 'CJ');
    get diagnostics v_n = row_count; v_cambiadas := v_cambiadas + v_n;
    -- c) todos los DISPLAY del SKU con el múltiplo de la ficha
    update maestra_sku m set multiplo = g.display_unidades
     where upper(btrim(m.sku)) = upper(g.sku) and upper(coalesce(m.unidad_medida, '')) in ('DISPLAY', 'DSP')
       and m.multiplo is distinct from g.display_unidades;
    -- d) DISPLAY con el EAN del display (si no está)
    if coalesce(g.ean_display, '') ~ '^[0-9]{8,14}$' then
      select * into r from maestra_sku where btrim(codigo_barras) = g.ean_display limit 1;
      if not found then
        insert into maestra_sku (sku, codigo_barras, descripcion, multiplo, unidad_medida, marca, requiere_vencimiento, activo)
        select upper(g.sku), g.ean_display, coalesce(max(m.descripcion), g.nombre), g.display_unidades, 'DISPLAY',
               max(m.marca), coalesce(bool_or(m.requiere_vencimiento), true), true
          from maestra_sku m where upper(btrim(m.sku)) = upper(g.sku);
        v_nuevas := v_nuevas + 1;
      elsif upper(btrim(r.sku)) <> upper(g.sku) then
        v_avisos := v_avisos || format(' %s: el EAN %s ya es de %s;', g.sku, g.ean_display, r.sku);
      elsif upper(coalesce(r.unidad_medida, '')) not in ('DISPLAY', 'DSP') then
        v_avisos := v_avisos || format(' %s: el EAN %s está como %s;', g.sku, g.ean_display, r.unidad_medida);
      end if;
    end if;
  end loop;
  raise notice 'CAJA eliminadas: %, CAJA pasadas a DISPLAY: %, DISPLAY nuevos con EAN: %.%', v_borradas, v_cambiadas, v_nuevas,
    case when v_avisos <> '' then ' Revisar:' || v_avisos else '' end;
end $$;

-- PASO 3 · Empaque sin caja: se cuentan displays (igual que el script 56)
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

grant execute on function public.wms_empaque_sku(text) to anon, authenticated, service_role;
grant execute on function public.wms_empaque_desglose(integer, integer, integer) to anon, authenticated, service_role;

-- Revisión final: cada SKU debe quedar con caja 0 (solo display) y display 6 o 12
select g.sku, e.multiplo_caja, e.multiplo_display,
       public.wms_empaque_desglose(g.pallet_unidades, e.multiplo_caja, e.multiplo_display) as pallet_completo
  from wms_sku_logistica g, lateral public.wms_empaque_sku(g.sku) e
 order by g.sku;
-- FIN 60
