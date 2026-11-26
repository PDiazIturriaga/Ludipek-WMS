-- =====================================================================================
-- 58a · Despachos de exportación: medidas del pallet, tara y peso (PARTE 1 de 3)
--   Agrega: largo/ancho/alto del pallet y tara por despacho; alto y peso de balanza por LPN;
--   Kg/un y Unidades/pallet en el pedido. Luego ejecute 58b y 58c.
--   Copie TODO el archivo (Ctrl+A) en el SQL editor de Supabase. Debe terminar en "-- FIN 58a".
-- =====================================================================================
alter table public.wms_despachos add column if not exists pallet_largo_m numeric default 1.20;
alter table public.wms_despachos add column if not exists pallet_ancho_m numeric default 0.80;
-- Pallet europeo (EPAL): 1,20 x 0,80 m, alto propio 0,144 m, peso aprox. 25 kg (la tara)
alter table public.wms_despachos alter column pallet_ancho_m set default 0.80;
alter table public.wms_despachos add column if not exists pallet_alto_m numeric;          -- alto total (m): carga + pallet de madera
alter table public.wms_despachos add column if not exists tara_pallet_kg numeric default 25;
alter table public.wms_despacho_lpn add column if not exists alto_m numeric;               -- si se midió ese pallet
alter table public.wms_despacho_lpn add column if not exists peso_bruto_kg numeric;        -- si se pesó en balanza
alter table public.wms_despacho_pedido add column if not exists kg_un numeric;             -- peso neto por unidad (pedido)
alter table public.wms_despacho_pedido add column if not exists unidades_pallet numeric;
-- Despachos que aún no tienen medidas pasan a pallet europeo (va después de crear todas las columnas)
update public.wms_despachos set pallet_ancho_m = 0.80 where pallet_ancho_m = 1.00 and pallet_alto_m is null;  -- aún sin medidas

-- Medidas generales del despacho (aplican a todos los pallets que no tengan medida propia)
create or replace function public.wms_despacho_medidas(p_id bigint, p_largo numeric, p_ancho numeric, p_alto numeric,
                                                       p_tara numeric, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  perform public.wms_usuario_despacho(p_usuario);
  if coalesce(p_largo, 1) <= 0 or coalesce(p_ancho, 1) <= 0 or coalesce(p_alto, 1) <= 0 or coalesce(p_alto, 0) > 3
     or coalesce(p_largo, 0) > 3 or coalesce(p_ancho, 0) > 3 then
    raise exception 'WMS: revise las medidas (en metros, ej. 1,20 x 1,00 x 1,50)';
  end if;
  if coalesce(p_tara, 0) < 0 or coalesce(p_tara, 0) > 200 then
    raise exception 'WMS: revise la tara del pallet (kg)';
  end if;
  update wms_despachos set pallet_largo_m = p_largo, pallet_ancho_m = p_ancho, pallet_alto_m = p_alto,
                           tara_pallet_kg = coalesce(p_tara, 0)
   where id = p_id and estado <> 'ANULADO';
  if not found then raise exception 'WMS: el despacho no existe o está anulado'; end if;
  return public.wms_despacho_detalle(p_id);
end $$;

-- Alto y/o peso de balanza de un pallet (null = usar el general)
create or replace function public.wms_despacho_lpn_medida(p_id bigint, p_lpn text, p_alto numeric, p_peso_bruto numeric,
                                                          p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  perform public.wms_usuario_despacho(p_usuario);
  if coalesce(p_alto, 1) <= 0 or coalesce(p_alto, 0) > 3 then raise exception 'WMS: el alto va en metros (ej. 1,45)'; end if;
  if coalesce(p_peso_bruto, 1) <= 0 or coalesce(p_peso_bruto, 0) > 3000 then raise exception 'WMS: revise el peso (kg)'; end if;
  update wms_despacho_lpn set alto_m = p_alto, peso_bruto_kg = p_peso_bruto
   where despacho_id = p_id and upper(btrim(lpn)) = upper(btrim(p_lpn));
  if not found then raise exception 'WMS: el LPN % no está en este despacho', p_lpn; end if;
  return public.wms_despacho_detalle(p_id);
end $$;

-- Pedido: ahora guarda también Kg/un y Unidades/pallet (p_lineas: [{sku, descripcion, unidades, pallets, kg_un, unidades_pallet}])
create or replace function public.wms_despacho_pedido_cargar(p_id bigint, p_lineas jsonb, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  perform public.wms_usuario_despacho(p_usuario);
  if not exists (select 1 from wms_despachos where id = p_id and estado = 'ABIERTO') then
    raise exception 'WMS: el despacho no está abierto';
  end if;
  delete from wms_despacho_pedido where despacho_id = p_id;
  insert into wms_despacho_pedido (despacho_id, sku, descripcion, unidades, pallets, kg_un, unidades_pallet)
  select p_id, upper(btrim(x->>'sku')), max(x->>'descripcion'),
         sum(coalesce(nullif(x->>'unidades', '')::numeric, 0))::int, sum(nullif(x->>'pallets', '')::numeric),
         max(nullif(x->>'kg_un', '')::numeric), max(nullif(x->>'unidades_pallet', '')::numeric)
    from jsonb_array_elements(coalesce(p_lineas, '[]'::jsonb)) x
   where nullif(btrim(x->>'sku'), '') is not null
   group by upper(btrim(x->>'sku'))
  having sum(coalesce(nullif(x->>'unidades', '')::numeric, 0)) > 0;
  return public.wms_despacho_detalle(p_id);
end $$;

grant execute on function public.wms_despacho_medidas(bigint, numeric, numeric, numeric, numeric, text) to authenticated, service_role;
grant execute on function public.wms_despacho_lpn_medida(bigint, text, numeric, numeric, text) to authenticated, service_role;
grant execute on function public.wms_despacho_pedido_cargar(bigint, jsonb, text) to authenticated, service_role;
notify pgrst, 'reload schema';
-- FIN 58a
