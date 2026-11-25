-- =====================================================================
-- LUDIPEK WMS · 49 OC POR PROVEEDOR (listado único)            (requiere 45, 46 y 48)
--
-- Se elige el proveedor (ej. VETPLUS) y se ven TODAS sus OC, como listado:
--   · datos de NetSuite: creada, esperada, estado, nota, unidades, si está recibida en NetSuite;
--   · lo del Panel de recepciones: si llegó físicamente (pallets, unidades, fechas), contenedores,
--     cita, y si salió el reporte de recepción.
-- Se puede ejecutar más de una vez.
-- =====================================================================
begin;

create or replace function public.wms_proveedor_normal(p text)
returns text language sql immutable as $$
  select nullif(upper(regexp_replace(btrim(coalesce(p, '')), '\s+', ' ', 'g')), '');
$$;

-- Proveedores con OC (NetSuite o WMS)
create or replace function public.wms_oc_proveedores()
returns jsonb language sql stable security definer set search_path = public as $$
  with ocs as (
    select public.wms_proveedor_normal(n.proveedor) prov, n.numero_oc, n.fecha_oc, n.abierta
      from wms_oc_netsuite n
    union
    select public.wms_proveedor_normal(a.proveedor), public.wms_numero_oc(a.numero_oc),
           coalesce(a.created_at, now())::date, false
      from asn_cabecera a
     where public.wms_numero_oc(a.numero_oc) is not null
       and not exists (select 1 from wms_oc_netsuite n where n.numero_oc = public.wms_numero_oc(a.numero_oc))
  )
  select coalesce(jsonb_agg(x order by x.ultima_oc desc nulls last, x.proveedor), '[]'::jsonb)
    from (select prov proveedor, count(distinct numero_oc)::int ocs,
                 count(distinct numero_oc) filter (where abierta)::int abiertas,
                 max(fecha_oc) ultima_oc
            from ocs where prov is not null group by prov) x;
$$;

-- Listado de OC del proveedor con todo lo que sabe el WMS
create or replace function public.wms_oc_por_proveedor(p_proveedor text, p_desde date default null)
returns jsonb language sql stable security definer set search_path = public as $$
  with prov as (select public.wms_proveedor_normal(p_proveedor) p),
  nums as (   -- OC del proveedor en NetSuite y en el WMS
    select n.numero_oc from wms_oc_netsuite n, prov where public.wms_proveedor_normal(n.proveedor) = prov.p
    union
    select public.wms_numero_oc(a.numero_oc) from asn_cabecera a, prov
     where public.wms_proveedor_normal(a.proveedor) = prov.p and public.wms_numero_oc(a.numero_oc) is not null
  ),
  filas as (
    select x.numero_oc,
           n.ns_id, coalesce(n.tranid, 'OC' || x.numero_oc) tranid,
           coalesce(n.proveedor, (select max(a.proveedor) from asn_cabecera a where public.wms_numero_oc(a.numero_oc) = x.numero_oc)) proveedor,
           coalesce(n.fecha_oc, (select min(a.created_at)::date from asn_cabecera a where public.wms_numero_oc(a.numero_oc) = x.numero_oc)) fecha_oc,
           n.creada_en, n.fecha_esperada, n.estado_ns, n.nota, n.abierta, n.ns_id is not null en_netsuite,
           public.wms_oc_estado_ns_recepcion(x.numero_oc) cargada_ns, n.recepcion_ns_fecha,
           a.ids asn_ids, a.estados estado_wms, a.unidades_esperadas,
           coalesce(n.unidades, a.unidades_esperadas) unidades_oc,
           r.pallets, r.unidades unidades_recibidas, r.cajas, r.primera primera_recepcion, r.ultima ultima_recepcion,
           c.contenedores, c.contenedores_recibidos, c.proxima_cita, c.ultima_cita,
           rep.estado reporte_estado, rep.enviado_en reporte_enviado_en, rep.enviado_a reporte_enviado_a
      from nums x
      left join wms_oc_netsuite n on n.numero_oc = x.numero_oc
      left join lateral (
        select array_agg(a.id order by a.id) ids, string_agg(distinct a.estado, ', ') estados,
               (select sum(d.unidades_esperadas)::int from asn_detalle d
                 where d.asn_id in (select a2.id from asn_cabecera a2 where public.wms_numero_oc(a2.numero_oc) = x.numero_oc)) unidades_esperadas
          from asn_cabecera a where public.wms_numero_oc(a.numero_oc) = x.numero_oc) a on true
      left join lateral (
        select count(distinct rr.lpn)::int pallets, sum(rr.unidades_totales)::int unidades, sum(rr.cajas)::int cajas,
               min(coalesce(rr.fecha_recepcion, rr.created_at)) primera, max(coalesce(rr.fecha_recepcion, rr.created_at)) ultima
          from registro_recepcion rr where rr.asn_id = any(a.ids)) r on true
      left join lateral (
        select count(*)::int contenedores, count(*) filter (where b.estado = 'RECIBIDO')::int contenedores_recibidos,
               min(b.cita) filter (where b.cita >= current_date) proxima_cita, max(b.cita) ultima_cita
          from public.wms_oc_contenedores_base(x.numero_oc) b) c on true
      left join lateral (
        select w.estado, w.enviado_en, w.enviado_a from wms_reportes_recepcion w
         where w.asn_id = any(a.ids) order by w.id desc limit 1) rep on true
  )
  select coalesce(jsonb_agg(to_jsonb(f) || jsonb_build_object(
           'tiene_oc', true,
           'en_wms', f.asn_ids is not null,
           'recibido_fisico', case
               when coalesce(f.unidades_recibidas, 0) = 0 then 'NO'
               when f.estado_wms ~* 'COMPLETADO|CERRAD' then 'SI'
               when coalesce(f.unidades_oc, 0) > 0 and f.unidades_recibidas >= f.unidades_oc then 'SI'
               else 'PARCIAL' end,
           'dias_creacion_a_llegada', case when f.primera_recepcion is not null and f.fecha_oc is not null
                                           then (f.primera_recepcion at time zone 'America/Santiago')::date - f.fecha_oc end,
           'dias_abierta', case when f.abierta and f.fecha_oc is not null then current_date - f.fecha_oc end)
         order by f.fecha_oc desc nulls last, f.numero_oc desc), '[]'::jsonb)
    from filas f
   where p_desde is null or f.fecha_oc is null or f.fecha_oc >= p_desde;
$$;

revoke execute on function public.wms_oc_proveedores() from public, anon;
revoke execute on function public.wms_oc_por_proveedor(text, date) from public, anon;
grant execute on function public.wms_oc_proveedores() to authenticated, service_role;
grant execute on function public.wms_oc_por_proveedor(text, date) to authenticated, service_role;
grant execute on function public.wms_proveedor_normal(text) to authenticated, service_role;

commit;

select x->>'proveedor' as proveedor, x->>'ocs' as ocs, x->>'abiertas' as abiertas
  from jsonb_array_elements(public.wms_oc_proveedores()) x limit 15;
