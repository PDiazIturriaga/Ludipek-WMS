-- 47 · Conciliar recepciones sin OC: pallets duplicados
-- La maestra tiene más de una fila por SKU (UNIDAD / CAJA). El cruce con la maestra repetía cada
-- registro de recepción y el panel mostraba pallets y unidades de más. Ahora se toma una sola
-- descripción por SKU. Requiere 33. Se puede ejecutar más de una vez.
begin;

create or replace function public.wms_recepciones_sin_oc(p_bodega text, p_desde date, p_hasta date)
returns table (id bigint, dia date, fecha_hora text, lpn text, sku text, descripcion text, lote text,
               vencimiento text, cajas integer, multiplo integer, unidades integer, contenedor text,
               operador text, estado_pallet text)
language sql stable security definer set search_path = public as $$
  select r.id,
         (coalesce(r.fecha_recepcion, r.created_at) at time zone 'America/Santiago')::date,
         to_char(coalesce(r.fecha_recepcion, r.created_at) at time zone 'America/Santiago', 'DD-MM-YYYY HH24:MI'),
         r.lpn::text, upper(btrim(r.sku))::text, m.descripcion::text, coalesce(r.lote, 'S/L')::text,
         coalesce(r.fecha_vencimiento_cl, to_char(r.fecha_vencimiento, 'DD-MM-YYYY'), '')::text,
         r.cajas, r.multiplo_aplicado, r.unidades_totales,
         nullif(nullif(upper(regexp_replace(btrim(r.contenedor), '\s+', '', 'g')), ''), 'SIN-CONTENEDOR'),
         r.operador::text, r.estado_pallet::text
    from public.registro_recepcion r
    left join lateral (
      select x.descripcion from public.maestra_sku x
       where upper(x.sku) = upper(btrim(r.sku)) and nullif(btrim(x.descripcion), '') is not null
       order by x.descripcion limit 1
    ) m on true
   where r.asn_id is null
     and coalesce(r.bodega, 'Bodega Santiago') = coalesce(p_bodega, 'Bodega Santiago')
     and coalesce(r.fecha_recepcion, r.created_at) >= (coalesce(p_desde, current_date - 30)::timestamp at time zone 'America/Santiago')
     and coalesce(r.fecha_recepcion, r.created_at) <  ((coalesce(p_hasta, current_date) + 1)::timestamp at time zone 'America/Santiago')
   order by 2, r.lpn, r.sku, r.id
   limit 5000
$$;

revoke all on function public.wms_recepciones_sin_oc(text, date, date) from public, anon, authenticated;
grant execute on function public.wms_recepciones_sin_oc(text, date, date) to service_role;

commit;

-- Revisión: debe dar la misma cantidad de filas que de registros (sin repetidos)
select count(*) as filas, count(distinct id) as registros
  from public.wms_recepciones_sin_oc('Bodega Santiago', current_date - 30, current_date);
