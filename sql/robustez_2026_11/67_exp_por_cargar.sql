-- =====================================================================
-- LUDIPEK WMS · 67 DESPACHOS DE EXPORTACIÓN CERRADOS → "POR CARGAR" EN CARGAS DE CAMIÓN  (requiere 58c)
-- Al cerrar un despacho EXP-… en Exportación, queda solo en Cargas de camión › Por cargar,
-- igual que las OT pickeadas. Desde ahí se crea la carga con un clic (patente y chofer) o se
-- agrega a una carga abierta.
--   · wms_exp_por_cargar(bodega): despachos CERRADOS (últimos 60 días) con pallets que aún no
--     salen en una carga cerrada. Si están en una carga abierta, se indica cuál.
--   · wms_carga_crear_con_despacho(...): crea la carga (contenedor y destino del despacho) y le
--     agrega el despacho, todo en una sola operación.
-- Se puede ejecutar las veces que quiera.
-- =====================================================================
begin;

create or replace function public.wms_exp_por_cargar(p_bodega text)
returns jsonb
language sql stable security definer set search_path = public as $$
  with d as (
    select d.*
    from wms_despachos d
    where d.bodega = public.wms_bodega_valida(p_bodega) and d.estado = 'CERRADO'
      and coalesce(d.cerrado_en, d.creado_en) > now() - interval '60 days'
  ),
  pend as (   -- pallets del despacho que todavía no salen en una carga cerrada
    select d.id, count(l.id) pallets_total,
           count(l.id) filter (where not exists (
             select 1 from wms_carga_items i join wms_cargas g on g.id = i.carga_id
             where g.estado = 'CERRADA' and i.despacho_id = d.id and i.estado = 'CARGADO'
               and upper(i.codigo) = upper(l.lpn))) pallets_por_cargar
    from d join wms_despacho_lpn l on l.despacho_id = d.id
    group by d.id
  )
  select coalesce(jsonb_agg(x order by x->>'cerrado_en' desc), '[]'::jsonb)
  from (
    select jsonb_build_object(
             'id', d.id, 'numero', d.numero, 'destino', d.destino, 'referencia', d.referencia,
             'contenedor', d.contenedor, 'stock_descontado', d.stock_descontado,
             'cerrado_en', d.cerrado_en, 'cerrado_por', d.cerrado_por,
             'pallets', p.pallets_total, 'pallets_por_cargar', p.pallets_por_cargar,
             'unidades', t->'totales'->'unidades', 'cajas', t->'totales'->'cajas', 'displays', t->'totales'->'displays',
             'peso_bruto_kg', t->'totales'->'peso_bruto_kg', 'm3', t->'totales'->'m3',
             'carga_abierta', (select g.numero from wms_carga_ordenes x join wms_cargas g on g.id = x.carga_id
                                where x.despacho_id = d.id and g.estado = 'ABIERTA' limit 1),
             'carga_abierta_id', (select g.id from wms_carga_ordenes x join wms_cargas g on g.id = x.carga_id
                                   where x.despacho_id = d.id and g.estado = 'ABIERTA' limit 1)) x
    from d join pend p on p.id = d.id
    cross join lateral (select public.wms_despacho_detalle(d.id) t) z
    where p.pallets_por_cargar > 0
  ) q;
$$;
grant execute on function public.wms_exp_por_cargar(text) to anon, authenticated, service_role;

create or replace function public.wms_carga_crear_con_despacho(
  p_bodega text, p_numero text, p_patente text, p_chofer text default null, p_usuario text default null)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  d record;
  v_carga jsonb;
begin
  select * into d from wms_despachos
   where upper(btrim(numero)) = upper(btrim(p_numero)) and bodega = public.wms_bodega_valida(p_bodega);
  if not found then raise exception 'WMS: no se encontró el despacho %', p_numero; end if;
  if d.estado <> 'CERRADO' then raise exception 'WMS: cierre el despacho % en Exportación antes de cargarlo', d.numero; end if;
  v_carga := public.wms_carga_crear(p_bodega, p_patente, d.contenedor, p_chofer,
                                    coalesce(nullif(btrim(d.destino), ''), 'Exportación'), p_usuario);
  return public.wms_carga_agregar_despacho((v_carga->>'id')::bigint, d.numero, p_usuario);
end $$;
grant execute on function public.wms_carga_crear_con_despacho(text, text, text, text, text) to anon, authenticated, service_role;

commit;

-- Revisión: despachos de exportación esperando camión
-- select x->>'numero' despacho, x->>'destino' destino, x->>'pallets_por_cargar' pallets, x->>'carga_abierta' en_carga
-- from jsonb_array_elements(public.wms_exp_por_cargar('Bodega Santiago')) x;

-- FIN 67
