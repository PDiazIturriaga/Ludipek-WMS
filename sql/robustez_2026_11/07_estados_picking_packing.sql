-- =====================================================================
-- LUDIPEK WMS · 07 CIERRE DE PICKING Y PACKING EN EL SERVIDOR  (requiere 01-04)
-- Antes, el celular actualizaba líneas y estado con escrituras sueltas y
-- silenciaba los errores: podía mostrar "pasó a PACKING" aunque Supabase
-- no cambiara el estado (caso OV 133409-FA, 18-11-2026).
-- Ahora cada cierre es UNA transacción que valida el flujo de estados,
-- deja historial en wms_historial_estados y responde OK o un error claro.
-- =====================================================================
begin;

-- Estados que usan PC y celular (el catálogo original no los tenía todos)
insert into public.wms_catalogo_estados (codigo, modulo, descripcion, orden_flujo, es_final, color_hex) values
  ('PENDIENTE',             'SALIDA',   'Pendiente',                 5,  false, '#64748B'),
  ('PENDIENTE_FACTURACION', 'SALIDA',   'Pendiente de facturación',  70, false, '#0284C7'),
  ('FACTURADO',             'SALIDA',   'Facturado',                 80, false, '#047857'),
  ('DESPACHADO',            'SALIDA',   'Despachado',                90, true,  '#047857'),
  ('ANULADO',               'SALIDA',   'Anulado',                   99, true,  '#B91C1C'),
  ('CERRADO',               'SALIDA',   'Cerrado',                   99, true,  '#475569')
on conflict (codigo) do nothing;

-- Orden del flujo de salida (para validar que no se retroceda por error)
create or replace function public.wms_orden_estado_ov(p text)
returns int language sql immutable as $$
  select case upper(coalesce(p, ''))
    when '' then 0 when 'PENDIENTE' then 5 when 'PENDIENTE_PICKING' then 10
    when 'PICKING_EN_PROCESO' then 20 when 'PICKING_COMPLETO' then 30
    when 'PENDIENTE_PACKING' then 40 when 'PACKING_EN_PROCESO' then 50
    when 'PENDIENTE_FACTURACION' then 70 when 'EN_TRANSITO_CCP' then 70
    when 'RECEPCION_CCP_EN_PROCESO' then 80 when 'FACTURADO' then 80
    when 'RECIBIDO_CCP' then 90 when 'RECIBIDO_CCP_CON_DIFERENCIAS' then 90
    when 'DESPACHADO' then 90 when 'ANULADO' then 99 when 'CERRADO' then 99
    else 50 end;
$$;

-- ---------------------------------------------------------------------
-- Cambio de estado validado (con historial). p_forzar permite a un
-- supervisor corregir un estado atrasado (ej. picking hecho pero la OV
-- quedó en PENDIENTE_PICKING).
-- ---------------------------------------------------------------------
create or replace function public.wms_cambiar_estado_ov(
  p_orden_id bigint, p_estado text, p_usuario text default null,
  p_observacion text default null, p_forzar boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o record;
  v_ant text;
  v_nuevo text := upper(btrim(coalesce(p_estado, '')));
begin
  select * into o from netsuite_ordenes_venta where id = p_orden_id for update;
  if not found then
    raise exception 'WMS: la orden % no existe', p_orden_id;
  end if;
  -- Bodega escrita distinto (ej. "Bodega Concepción"): la regla ck_ov_bodega_valida rechazaría el cambio
  update netsuite_ordenes_venta set bodega = public.wms_bodega_valida(bodega)
   where id = p_orden_id and bodega is not null and bodega not in ('Bodega Santiago', 'Bodega Concepcion');
  select * into o from netsuite_ordenes_venta where id = p_orden_id;
  v_ant := upper(coalesce(nullif(btrim(o.estado_ns), ''), nullif(btrim(o.estado), ''), 'PENDIENTE'));
  if v_ant = v_nuevo then
    return jsonb_build_object('numero_ov', o.numero_ov, 'estado_anterior', v_ant, 'estado_nuevo', v_nuevo, 'sin_cambios', true);
  end if;
  if v_ant in ('ANULADO', 'CERRADO', 'DESPACHADO') and not p_forzar then
    raise exception 'WMS: la orden % está %, no se puede modificar', o.numero_ov, v_ant;
  end if;
  if public.wms_orden_estado_ov(v_nuevo) < public.wms_orden_estado_ov(v_ant) and not p_forzar then
    raise exception 'WMS: la orden % ya está en % y no puede volver a %', o.numero_ov, v_ant, v_nuevo;
  end if;

  insert into wms_catalogo_estados (codigo, modulo, descripcion) values (v_nuevo, 'SALIDA', v_nuevo)
  on conflict (codigo) do nothing;
  update netsuite_ordenes_venta set estado_ns = v_nuevo, estado = v_nuevo, updated_at = now() where id = p_orden_id;
  insert into wms_historial_estados (entidad_tipo, entidad_id, documento, estado_anterior, estado_nuevo, usuario, bodega, observacion)
  values ('ORDEN_VENTA', p_orden_id, o.numero_ov, v_ant, v_nuevo,
          coalesce(nullif(upper(btrim(p_usuario)), ''), 'APP'), o.bodega,
          coalesce(p_observacion, case when p_forzar then 'Corrección manual de estado' end));
  return jsonb_build_object('numero_ov', o.numero_ov, 'estado_anterior', v_ant, 'estado_nuevo', v_nuevo);
end $$;

-- ---------------------------------------------------------------------
-- Cierre de PICKING: guarda cantidades y lotes de cada línea y pasa la
-- orden a PENDIENTE_PACKING, todo o nada.
-- p_lineas: [{"id": 10042, "cantidad_pickeada": 2, "lotes_pickeados": "L1 / 22-05-2028 (2 UN)"}]
-- ---------------------------------------------------------------------
create or replace function public.wms_cerrar_picking(p_orden_id bigint, p_lineas jsonb, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  l jsonb;
  d record;
  v_cant int;
  v_total int := 0;
  v_pedido int := 0;
  v_estado jsonb;
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
                format('Picking cerrado: %s de %s UN', v_total, v_pedido));
  return v_estado || jsonb_build_object('unidades_pickeadas', v_total, 'unidades_pedidas', v_pedido);
end $$;

-- ---------------------------------------------------------------------
-- Cierre de PACKING.
--  p_modo 'BULTOS'  : OV normales/farmacia -> N° de bultos y peso.
--  p_modo 'PALLETS' : traslados OT -> cada ítem debe traer su LPN de pallet.
--  p_detalle: [{"id_detalle", "sku", "descripcion", "unidades_totales", "lote",
--               "fecha_vencimiento_cl", "lpn_pallet", ...}]  (un ítem por SKU/lote/pallet)
--  La cantidad empacada de cada línea es la SUMA de sus ítems (antes quedaba
--  la del último pallet). Traslados OT-* pasan a EN_TRANSITO_CCP; el resto a
--  PENDIENTE_FACTURACION.
-- ---------------------------------------------------------------------
create or replace function public.wms_cerrar_packing(
  p_orden_id bigint, p_modo text, p_detalle jsonb, p_bultos int,
  p_tipo_empaque text default null, p_comuna text default null, p_lpn text default null,
  p_peso_esperado_kg numeric default null, p_peso_real_kg numeric default null,
  p_borrador_id bigint default null, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o record;
  v_modo text := upper(coalesce(p_modo, 'BULTOS'));
  v_usuario text := coalesce(nullif(upper(btrim(p_usuario)), ''), 'PACKING_RF');
  v_destino text;
  v_lpn text := nullif(upper(btrim(coalesce(p_lpn, ''))), '');
  r record;
  v_pl_id bigint;
  v_estado jsonb;
  v_canal text;
  v_total int;
begin
  select * into o from netsuite_ordenes_venta where id = p_orden_id for update;
  if not found then raise exception 'WMS: la orden % no existe', p_orden_id; end if;
  -- Bodega escrita distinto (ej. "Bodega Concepción"): la regla ck_ov_bodega_valida rechazaría el cambio
  update netsuite_ordenes_venta set bodega = public.wms_bodega_valida(bodega)
   where id = p_orden_id and bodega is not null and bodega not in ('Bodega Santiago', 'Bodega Concepcion');
  select * into o from netsuite_ordenes_venta where id = p_orden_id;
  if v_modo not in ('BULTOS', 'PALLETS') then raise exception 'WMS: modo de packing inválido %', p_modo; end if;
  if jsonb_typeof(p_detalle) is distinct from 'array' or jsonb_array_length(p_detalle) = 0 then
    raise exception 'WMS: el packing no tiene productos';
  end if;
  if coalesce(p_bultos, 0) < 1 then raise exception 'WMS: indique la cantidad de bultos'; end if;
  if v_modo = 'PALLETS' and exists (select 1 from jsonb_array_elements(p_detalle) x
                                    where coalesce(btrim(x->>'lpn_pallet'), '') = '') then
    raise exception 'WMS: en un traslado cada producto debe ir en un pallet con LPN';
  end if;
  if public.wms_orden_estado_ov(coalesce(o.estado_ns, o.estado)) >= 70 then
    raise exception 'WMS: la orden % ya fue empacada (%)', o.numero_ov, coalesce(o.estado_ns, o.estado);
  end if;

  -- Cantidad empacada por línea = suma de sus ítems
  for r in
    select (x->>'id_detalle')::bigint as id_det,
           sum(coalesce((x->>'unidades_totales')::int, 0)) as unidades,
           string_agg(coalesce('[' || nullif(x->>'lpn_pallet', '') || '] ', '') || coalesce(x->>'lote', 'S/L') || ' / '
                      || coalesce(nullif(x->>'fecha_vencimiento_cl', ''), 'S/F') || ' (' || coalesce(x->>'unidades_totales', '0') || ' UN)', ' | ') as traza
    from jsonb_array_elements(p_detalle) x
    where x->>'id_detalle' is not null
    group by 1
  loop
    update netsuite_detalle_ov
       set cantidad_pickeada = r.unidades, lotes_pickeados = r.traza,
           estado_linea = case when v_modo = 'PALLETS' then 'CONSOLIDADO_LPN' else 'EMPACADO' end
     where id = r.id_det and orden_id = p_orden_id;
    if not found then
      raise exception 'WMS: la línea % no pertenece a la orden %', r.id_det, p_orden_id;
    end if;
  end loop;
  select coalesce(sum(cantidad_pickeada), 0) into v_total from netsuite_detalle_ov where orden_id = p_orden_id;

  -- Packing list (actualiza el borrador de pallets si existe)
  if p_borrador_id is not null and exists (select 1 from wms_packing_lists_fa where id = p_borrador_id and orden_id = p_orden_id) then
    update wms_packing_lists_fa set detalle_json = p_detalle, usuario_picking = v_usuario, fecha_emision = now(), bodega = o.bodega
     where id = p_borrador_id returning id into v_pl_id;
  else
    insert into wms_packing_lists_fa (orden_id, numero_ov, cliente_nombre, usuario_picking, detalle_json, fecha_emision, bodega)
    values (p_orden_id, o.numero_ov, o.cliente_nombre, v_usuario, p_detalle, now(), o.bodega)
    returning id into v_pl_id;
  end if;

  -- canal_venta conserva el canal original y agrega los datos del despacho
  select string_agg(p, '|') into v_canal
  from (select btrim(p) p from unnest(string_to_array(coalesce(o.canal_venta, ''), '|')) p
        where btrim(p) <> '' and upper(btrim(p)) !~ '^(LPN|BULTOS|TIPO|COMUNA|PESO_KG):') z;
  v_canal := concat_ws('|', nullif(v_canal, ''),
                       case when v_lpn is not null then 'LPN:' || v_lpn end,
                       'BULTOS:' || p_bultos,
                       case when nullif(btrim(p_tipo_empaque), '') is not null then 'TIPO:' || upper(btrim(p_tipo_empaque)) end,
                       case when nullif(btrim(p_comuna), '') is not null then 'COMUNA:' || upper(btrim(p_comuna)) end,
                       case when p_peso_real_kg is not null then 'PESO_KG:' || round(p_peso_real_kg, 2)
                            when p_peso_esperado_kg is not null then 'PESO_KG:' || round(p_peso_esperado_kg, 2) end);
  update netsuite_ordenes_venta set canal_venta = v_canal where id = p_orden_id;

  v_destino := case when upper(o.numero_ov) like 'OT-%' then 'EN_TRANSITO_CCP' else 'PENDIENTE_FACTURACION' end;
  v_estado := public.wms_cambiar_estado_ov(p_orden_id, v_destino, v_usuario,
      format('Packing %s: %s bultos, %s UN%s', v_modo, p_bultos, v_total,
             case when p_peso_real_kg is not null then ', ' || round(p_peso_real_kg, 2) || ' kg reales' else '' end),
      true);
  return v_estado || jsonb_build_object('packing_list_id', v_pl_id, 'unidades', v_total, 'bultos', p_bultos);
end $$;

revoke all on function public.wms_cambiar_estado_ov(bigint, text, text, text, boolean) from public;
grant execute on function public.wms_cambiar_estado_ov(bigint, text, text, text, boolean) to anon, authenticated, service_role;
grant execute on function public.wms_cerrar_picking(bigint, jsonb, text) to anon, authenticated, service_role;
grant execute on function public.wms_cerrar_packing(bigint, text, jsonb, integer, text, text, text, numeric, numeric, bigint, text) to anon, authenticated, service_role;

commit;
