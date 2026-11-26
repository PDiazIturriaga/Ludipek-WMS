-- =====================================================================================
-- 58c · Cargas de camión con despachos de exportación (PARTE 3 de 3; antes ejecute 58a y 58b)
--   En "Cargas de camión" se puede agregar un despacho EXP-... igual que una OT u OV: sus pallets
--   (LPN escaneados) quedan para subir al camión, con peso bruto y m³.
--   Copie TODO el archivo (Ctrl+A) en el SQL editor de Supabase. Debe terminar en "-- FIN 58c".
-- =====================================================================================
alter table public.wms_carga_ordenes alter column orden_id drop not null;
alter table public.wms_carga_ordenes add column if not exists despacho_id bigint references public.wms_despachos(id) on delete cascade;
alter table public.wms_carga_items alter column orden_id drop not null;
alter table public.wms_carga_items add column if not exists despacho_id bigint references public.wms_despachos(id) on delete cascade;
alter table public.wms_carga_items add column if not exists peso_kg numeric;
alter table public.wms_carga_items add column if not exists m3 numeric;
alter table public.wms_carga_ordenes drop constraint if exists wms_carga_ordenes_tipo_check;
alter table public.wms_carga_ordenes add constraint wms_carga_ordenes_tipo_check check (tipo in ('OT', 'OV', 'EXP'));
create unique index if not exists ux_carga_ordenes_despacho on public.wms_carga_ordenes (carga_id, despacho_id) where despacho_id is not null;

-- Agregar un despacho de exportación a la carga: un ítem por pallet (LPN) escaneado
create or replace function public.wms_carga_agregar_despacho(p_carga_id bigint, p_numero text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  c record;
  d record;
  v_usuario text := public.wms_usuario_carga(p_usuario);
  v_det jsonb;
  v_otra text;
  v_n int := 0;
  l jsonb;
begin
  select * into c from wms_cargas where id = p_carga_id for update;
  if not found then raise exception 'WMS: la carga % no existe', p_carga_id; end if;
  if c.estado <> 'ABIERTA' then raise exception 'WMS: la carga % está %', c.numero, c.estado; end if;
  select * into d from wms_despachos
   where upper(btrim(numero)) = upper(btrim(p_numero)) and bodega = c.bodega;
  if not found then raise exception 'WMS: no se encontró el despacho % en %', p_numero, c.bodega; end if;
  if d.estado = 'ANULADO' then raise exception 'WMS: el despacho % está anulado', d.numero; end if;
  if exists (select 1 from wms_carga_ordenes where carga_id = c.id and despacho_id = d.id) then
    raise exception 'WMS: el despacho % ya está en esta carga', d.numero;
  end if;
  select g.numero into v_otra from wms_carga_ordenes x join wms_cargas g on g.id = x.carga_id
   where x.despacho_id = d.id and g.estado = 'ABIERTA' limit 1;
  if v_otra is not null then raise exception 'WMS: el despacho % ya está en la carga %', d.numero, v_otra; end if;

  v_det := public.wms_despacho_detalle(d.id);
  if jsonb_array_length(coalesce(v_det->'lpns', '[]'::jsonb)) = 0 then
    raise exception 'WMS: el despacho % no tiene pallets escaneados', d.numero;
  end if;
  insert into wms_carga_ordenes (carga_id, orden_id, despacho_id, numero_ov, tipo, agregado_por)
  values (c.id, null, d.id, d.numero, 'EXP', v_usuario);
  for l in select x from jsonb_array_elements(v_det->'lpns') x order by x->>'escaneado_en' loop
    -- un pallet que ya salió en otra carga cerrada no se vuelve a cargar
    continue when exists (select 1 from wms_carga_items i join wms_cargas g on g.id = i.carga_id
                           where g.estado = 'CERRADA' and i.despacho_id = d.id and i.estado = 'CARGADO'
                             and upper(i.codigo) = upper(l->>'lpn'));
    v_n := v_n + 1;
    insert into wms_carga_items (carga_id, orden_id, despacho_id, numero_ov, tipo, codigo, n, total, cajas, unidades, peso_kg, m3)
    values (c.id, null, d.id, d.numero, 'PALLET', upper(l->>'lpn'), v_n, 1,
            (select sum(coalesce((z->'empaque'->>'cajas')::int, 0)) from jsonb_array_elements(l->'contenido') z),
            (l->>'unidades')::int, (l->>'peso_bruto_kg')::numeric, (l->>'m3')::numeric)
    on conflict (carga_id, codigo) do nothing;
  end loop;
  if v_n = 0 then raise exception 'WMS: los pallets del despacho % ya salieron en una carga anterior', d.numero; end if;
  update wms_carga_items set total = v_n where carga_id = c.id and despacho_id = d.id;
  if c.contenedor is null and d.contenedor is not null then
    update wms_cargas set contenedor = d.contenedor where id = c.id;
  end if;
  return public.wms_carga_detalle(c.id);
end $$;

-- "Agregar" de la carga (PC y celular): si el número es un despacho EXP-..., lo agrega como exportación
do $$
declare v_def text;
begin
  v_def := pg_get_functiondef('public.wms_carga_agregar_orden(bigint, text, text)'::regprocedure);
  if position('wms_carga_agregar_despacho' in v_def) = 0 then
    execute 'alter function public.wms_carga_agregar_orden(bigint, text, text) rename to wms_carga_agregar_orden_ns';
  end if;
end $$;

create or replace function public.wms_carga_agregar_orden(p_carga_id bigint, p_numero text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  if upper(btrim(coalesce(p_numero, ''))) like 'EXP-%' then
    return public.wms_carga_agregar_despacho(p_carga_id, p_numero, p_usuario);
  end if;
  return public.wms_carga_agregar_orden_ns(p_carga_id, p_numero, p_usuario);    -- OT / OV de NetSuite (como antes)
end $$;

-- Detalle de la carga: ahora incluye despachos de exportación, peso y m³
create or replace function public.wms_carga_detalle(p_carga_id bigint)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare
  c record;
begin
  select * into c from wms_cargas where id = p_carga_id;
  if not found then raise exception 'WMS: la carga % no existe', p_carga_id; end if;
  return to_jsonb(c) || jsonb_build_object(
    'total',      (select count(*) from wms_carga_items where carga_id = c.id and estado <> 'QUITADO'),
    'cargados',   (select count(*) from wms_carga_items where carga_id = c.id and estado = 'CARGADO'),
    'pendientes', (select count(*) from wms_carga_items where carga_id = c.id and estado = 'PENDIENTE'),
    'quitados',   (select count(*) from wms_carga_items where carga_id = c.id and estado = 'QUITADO'),
    'unidades',   (select coalesce(sum(unidades), 0) from wms_carga_items where carga_id = c.id and estado <> 'QUITADO'),
    'peso_kg',    (select round(sum(peso_kg), 1) from wms_carga_items where carga_id = c.id and estado <> 'QUITADO'),
    'm3',         (select round(sum(m3), 2) from wms_carga_items where carga_id = c.id and estado <> 'QUITADO'),
    'ordenes', coalesce((
      select jsonb_agg(jsonb_build_object(
               'orden_id', o.orden_id, 'despacho_id', o.despacho_id, 'numero_ov', o.numero_ov, 'tipo', o.tipo,
               'cliente', coalesce(v.cliente_nombre, case when o.tipo = 'EXP' then 'Exportación ' || coalesce(dx.destino, '') end),
               'estado_orden', coalesce(upper(coalesce(v.estado_ns, v.estado)), dx.estado),
               'total', (select count(*) from wms_carga_items i where i.carga_id = c.id
                          and (i.orden_id = o.orden_id or i.despacho_id = o.despacho_id) and i.estado <> 'QUITADO'),
               'cargados', (select count(*) from wms_carga_items i where i.carga_id = c.id
                             and (i.orden_id = o.orden_id or i.despacho_id = o.despacho_id) and i.estado = 'CARGADO'),
               'items', coalesce((select jsonb_agg(jsonb_build_object(
                          'id', i.id, 'tipo', i.tipo, 'codigo', i.codigo, 'n', i.n, 'total', i.total,
                          'cajas', i.cajas, 'unidades', i.unidades, 'peso_kg', i.peso_kg, 'm3', i.m3, 'estado', i.estado,
                          'cargado_por', i.cargado_por, 'cargado_en', i.cargado_en, 'motivo', i.motivo) order by i.n)
                        from wms_carga_items i where i.carga_id = c.id
                         and (i.orden_id = o.orden_id or i.despacho_id = o.despacho_id)), '[]'::jsonb))
             order by o.id)
      from wms_carga_ordenes o
      left join netsuite_ordenes_venta v on v.id = o.orden_id
      left join wms_despachos dx on dx.id = o.despacho_id
      where o.carga_id = c.id), '[]'::jsonb));
end $$;

-- Sacar una orden o un despacho de la carga (el celular envía p_despacho_id para los EXP)
drop function if exists public.wms_carga_quitar_orden(bigint, bigint, text);
create or replace function public.wms_carga_quitar_orden(p_carga_id bigint, p_orden_id bigint, p_usuario text default null,
                                                         p_despacho_id bigint default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  c record;
begin
  perform public.wms_usuario_carga(p_usuario);
  select * into c from wms_cargas where id = p_carga_id for update;
  if not found or c.estado <> 'ABIERTA' then raise exception 'WMS: la carga no está abierta'; end if;
  if p_orden_id is null and p_despacho_id is null then raise exception 'WMS: indique la orden o el despacho'; end if;
  if exists (select 1 from wms_carga_items where carga_id = c.id and estado = 'CARGADO'
              and (orden_id = p_orden_id or despacho_id = p_despacho_id)) then
    raise exception 'WMS: esa orden ya tiene pallets/bultos cargados. Desmárquelos antes de sacarla de la carga.';
  end if;
  delete from wms_carga_items where carga_id = c.id and (orden_id = p_orden_id or despacho_id = p_despacho_id);
  delete from wms_carga_ordenes where carga_id = c.id and (orden_id = p_orden_id or despacho_id = p_despacho_id);
  return public.wms_carga_detalle(c.id);
end $$;

grant execute on function public.wms_carga_quitar_orden(bigint, bigint, text, bigint) to anon, authenticated, service_role;
grant execute on function public.wms_carga_agregar_despacho(bigint, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_carga_agregar_orden(bigint, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_carga_agregar_orden_ns(bigint, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_carga_detalle(bigint) to anon, authenticated, service_role;
notify pgrst, 'reload schema';
-- FIN 58c
