-- =====================================================================
-- LUDIPEK WMS · 11 MESAS DE PACKING  (requiere 07 y 10)
-- Flujo: el picker termina en el celular y deja el pedido en una mesa
-- (MESA 1 a MESA 6, QR "Mesa N" pegado en cada mesa). El packer escanea
-- la mesa, ve las OV que esperan ahí y las procesa.
-- La mesa queda guardada en la orden: el PC muestra qué hay en cada mesa.
-- =====================================================================
begin;

alter table public.netsuite_ordenes_venta
  add column if not exists mesa_packing text,
  add column if not exists mesa_asignada_en timestamptz,
  add column if not exists mesa_asignada_por text;

create index if not exists idx_ov_mesa_packing on public.netsuite_ordenes_venta (bodega, mesa_packing)
  where mesa_packing is not null;

-- "Mesa 3", "MESA-3", "mesa3", "3" -> "MESA 3"
create or replace function public.wms_normalizar_mesa(p text)
returns text language plpgsql immutable as $$
declare
  v_num text := substring(upper(coalesce(p, '')) from '(\d{1,2})');
begin
  if v_num is null then return null; end if;
  if v_num::int < 1 or v_num::int > 20 then
    raise exception 'WMS: mesa de packing inválida (%)', p;
  end if;
  return 'MESA ' || v_num::int;
end $$;

do $$ begin
  alter table public.netsuite_ordenes_venta add constraint ck_ov_mesa_packing
    check (mesa_packing is null or mesa_packing ~ '^MESA [1-9][0-9]?$');
exception when duplicate_object then null; end $$;

-- ---------------------------------------------------------------------
-- Asignar o cambiar la mesa de una orden (picker al terminar, o el PC)
-- ---------------------------------------------------------------------
create or replace function public.wms_asignar_mesa_packing(p_orden_id bigint, p_mesa text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o record;
  v_mesa text := public.wms_normalizar_mesa(p_mesa);
begin
  if v_mesa is null then raise exception 'WMS: indique la mesa de packing'; end if;
  select * into o from netsuite_ordenes_venta where id = p_orden_id for update;
  if not found then raise exception 'WMS: la orden % no existe', p_orden_id; end if;
  if public.wms_orden_estado_ov(coalesce(o.estado_ns, o.estado)) >= 70 then
    raise exception 'WMS: la orden % ya fue empacada; no se le asigna mesa', o.numero_ov;
  end if;
  update netsuite_ordenes_venta
     set mesa_packing = v_mesa, mesa_asignada_en = now(),
         mesa_asignada_por = coalesce(nullif(upper(btrim(p_usuario)), ''), 'APP')
   where id = p_orden_id;
  insert into wms_historial_estados (entidad_tipo, entidad_id, documento, estado_anterior, estado_nuevo, usuario, bodega, observacion)
  values ('ORDEN_VENTA', p_orden_id, o.numero_ov,
          upper(coalesce(nullif(o.estado_ns, ''), 'PENDIENTE')), upper(coalesce(nullif(o.estado_ns, ''), 'PENDIENTE')),
          coalesce(nullif(upper(btrim(p_usuario)), ''), 'APP'), o.bodega,
          'Pedido dejado en ' || v_mesa || coalesce(' (antes ' || o.mesa_packing || ')', ''));
  return jsonb_build_object('numero_ov', o.numero_ov, 'mesa', v_mesa);
end $$;

-- ---------------------------------------------------------------------
-- Cierre de picking con mesa (reemplaza la versión de 07)
-- ---------------------------------------------------------------------
drop function if exists public.wms_cerrar_picking(bigint, jsonb, text);

create or replace function public.wms_cerrar_picking(
  p_orden_id bigint, p_lineas jsonb, p_usuario text default null, p_mesa text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  l jsonb;
  d record;
  v_cant int;
  v_total int := 0;
  v_pedido int := 0;
  v_estado jsonb;
  v_mesa text := public.wms_normalizar_mesa(p_mesa);
begin
  if not exists (select 1 from netsuite_ordenes_venta where id = p_orden_id) then
    raise exception 'WMS: la orden % no existe', p_orden_id;
  end if;
  for l in select * from jsonb_array_elements(coalesce(p_lineas, '[]'::jsonb)) loop
    select * into d from netsuite_detalle_ov where id = (l->>'id')::bigint and orden_id = p_orden_id for update;
    if not found then
      raise exception 'WMS: la línea % no pertenece a la orden %', l->>'id', p_orden_id;
    end if;
    v_cant := greatest(coalesce((l->>'cantidad_pickeada')::int, 0), 0);
    if v_cant > d.cantidad_pedida then
      raise exception 'WMS: SKU %: se pickearon % UN y la orden pide %', d.sku, v_cant, d.cantidad_pedida;
    end if;
    update netsuite_detalle_ov
       set cantidad_pickeada = v_cant,
           lotes_pickeados = nullif(l->>'lotes_pickeados', ''),
           estado_linea = case when v_cant >= d.cantidad_pedida then 'PICKEADO'
                               when v_cant > 0 then 'PICKEADO_PARCIAL' else 'SIN_STOCK' end
     where id = d.id;
  end loop;

  select coalesce(sum(cantidad_pickeada), 0), coalesce(sum(cantidad_pedida), 0) into v_total, v_pedido
  from netsuite_detalle_ov where orden_id = p_orden_id;
  if v_total = 0 then
    raise exception 'WMS: no hay unidades pickeadas; la orden no puede pasar a packing';
  end if;

  v_estado := public.wms_cambiar_estado_ov(p_orden_id, 'PENDIENTE_PACKING', p_usuario,
                format('Picking cerrado: %s de %s UN%s', v_total, v_pedido, coalesce(' · dejado en ' || v_mesa, '')));
  if v_mesa is not null then
    update netsuite_ordenes_venta
       set mesa_packing = v_mesa, mesa_asignada_en = now(),
           mesa_asignada_por = coalesce(nullif(upper(btrim(p_usuario)), ''), 'APP')
     where id = p_orden_id;
  end if;
  return v_estado || jsonb_build_object('unidades_pickeadas', v_total, 'unidades_pedidas', v_pedido, 'mesa', v_mesa);
end $$;

-- ---------------------------------------------------------------------
-- Órdenes esperando en una mesa (o en todas, si p_mesa es null)
-- ---------------------------------------------------------------------
create or replace function public.wms_ordenes_en_mesa(p_bodega text, p_mesa text default null)
returns table (id bigint, numero_ov text, cliente_nombre text, mesa_packing text, estado_ns text,
               mesa_asignada_en timestamptz, lineas integer, unidades integer)
language sql stable security definer set search_path = public as $$
  select o.id::bigint, o.numero_ov, o.cliente_nombre, o.mesa_packing, o.estado_ns, o.mesa_asignada_en,
         (select count(*) from netsuite_detalle_ov d where d.orden_id = o.id and coalesce(d.cantidad_pickeada, 0) > 0)::int,
         (select coalesce(sum(d.cantidad_pickeada), 0) from netsuite_detalle_ov d where d.orden_id = o.id)::int
  from netsuite_ordenes_venta o
  where coalesce(o.bodega, 'Bodega Santiago') = public.wms_bodega_valida(p_bodega)
    and o.mesa_packing is not null
    and (p_mesa is null or o.mesa_packing = public.wms_normalizar_mesa(p_mesa))
    and upper(coalesce(o.estado_ns, '')) in ('PENDIENTE_PACKING', 'PACKING_EN_PROCESO')
  order by o.mesa_packing, o.mesa_asignada_en;
$$;

grant execute on function public.wms_normalizar_mesa(text) to anon, authenticated, service_role;
grant execute on function public.wms_asignar_mesa_packing(bigint, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_cerrar_picking(bigint, jsonb, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_ordenes_en_mesa(text, text) to anon, authenticated, service_role;

commit;
