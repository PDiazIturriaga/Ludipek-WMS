-- =====================================================================
-- LUDIPEK WMS · 10 PACKING: VALIDACIÓN CLARA Y CIERRE CON FALTANTE  (requiere 07)
-- 1) Antes, si el celular mandaba más unidades que las pickeadas, la base
--    respondía con un error técnico (ck_det_pickeado_rango). Ahora valida
--    línea por línea y responde en español qué SKU está mal.
-- 2) Se puede cerrar el packing con faltante indicando un motivo. Queda:
--    · en la orden (canal_venta "FALTANTE:n" -> el PC lo muestra en rojo),
--    · en el historial de estados (motivo y detalle),
--    · en historial_movimientos como FALTANTE_PACKING por SKU (para conteo).
-- =====================================================================
begin;

drop function if exists public.wms_cerrar_packing(bigint, text, jsonb, integer, text, text, text, numeric, numeric, bigint, text);

create or replace function public.wms_cerrar_packing(
  p_orden_id bigint, p_modo text, p_detalle jsonb, p_bultos int,
  p_tipo_empaque text default null, p_comuna text default null, p_lpn text default null,
  p_peso_esperado_kg numeric default null, p_peso_real_kg numeric default null,
  p_borrador_id bigint default null, p_usuario text default null,
  p_motivo_faltante text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o record;
  d record;
  v_modo text := upper(coalesce(p_modo, 'BULTOS'));
  v_usuario text := coalesce(nullif(upper(btrim(p_usuario)), ''), 'PACKING_RF');
  v_motivo text := nullif(btrim(coalesce(p_motivo_faltante, '')), '');
  v_destino text;
  v_lpn text := nullif(upper(btrim(coalesce(p_lpn, ''))), '');
  v_pl_id bigint;
  v_estado jsonb;
  v_canal text;
  v_total int;
  v_faltante int := 0;
  v_detalle_falt text := '';
  v_emp int;
  v_traza text;
begin
  select * into o from netsuite_ordenes_venta where id = p_orden_id for update;
  if not found then raise exception 'WMS: la orden % no existe', p_orden_id; end if;
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
  if exists (select 1 from jsonb_array_elements(p_detalle) x
             where x->>'id_detalle' is not null
               and not exists (select 1 from netsuite_detalle_ov n where n.id = (x->>'id_detalle')::bigint and n.orden_id = p_orden_id)) then
    raise exception 'WMS: el packing trae productos que no son de la orden %', o.numero_ov;
  end if;

  -- 1) Validar cada línea: empacado <= pickeado, y calcular faltantes
  for d in select * from netsuite_detalle_ov where orden_id = p_orden_id order by id for update loop
    select coalesce(sum(coalesce((x->>'unidades_totales')::int, 0)), 0) into v_emp
    from jsonb_array_elements(p_detalle) x where (x->>'id_detalle')::bigint = d.id;
    if v_emp > coalesce(d.cantidad_pickeada, 0) then
      raise exception 'WMS: SKU %: se están empacando % UN pero se pickearon %. Revise la verificación de esa línea.',
        d.sku, v_emp, coalesce(d.cantidad_pickeada, 0);
    end if;
    if v_emp < coalesce(d.cantidad_pickeada, 0) then
      v_faltante := v_faltante + (d.cantidad_pickeada - v_emp);
      v_detalle_falt := v_detalle_falt || format('%s: %s de %s UN; ', d.sku, v_emp, d.cantidad_pickeada);
    end if;
  end loop;
  if v_faltante > 0 and v_motivo is null then
    raise exception 'WMS: faltan % UN por empacar (%). Para cerrar así use "Cerrar con faltante" e indique el motivo.',
      v_faltante, rtrim(v_detalle_falt, '; ');
  end if;

  -- 2) Guardar lo empacado por línea (y registrar el faltante para conteo)
  for d in select * from netsuite_detalle_ov where orden_id = p_orden_id order by id loop
    select coalesce(sum(coalesce((x->>'unidades_totales')::int, 0)), 0),
           string_agg(coalesce('[' || nullif(x->>'lpn_pallet', '') || '] ', '') || coalesce(x->>'lote', 'S/L') || ' / '
                      || coalesce(nullif(x->>'fecha_vencimiento_cl', ''), 'S/F') || ' (' || coalesce(x->>'unidades_totales', '0') || ' UN)', ' | ')
      into v_emp, v_traza
    from jsonb_array_elements(p_detalle) x where (x->>'id_detalle')::bigint = d.id;
    if coalesce(d.cantidad_pickeada, 0) = 0 then
      continue;  -- quiebre de picking: la línea no viaja
    end if;
    update netsuite_detalle_ov
       set cantidad_pickeada = v_emp,
           lotes_pickeados = coalesce(v_traza, lotes_pickeados),
           estado_linea = case when v_emp < d.cantidad_pickeada then 'EMPACADO_CON_FALTANTE'
                               when v_modo = 'PALLETS' then 'CONSOLIDADO_LPN' else 'EMPACADO' end
     where id = d.id;
    if v_emp < d.cantidad_pickeada then
      insert into historial_movimientos (bodega, usuario, tipo_movimiento, lpn, sku, lote, ubicacion_origen, ubicacion_destino,
                                         cajas_afectadas, unidades_afectadas)
      values (coalesce(o.bodega, 'Bodega Santiago'), v_usuario, 'FALTANTE_PACKING (' || o.numero_ov || ')', null, d.sku,
              coalesce(nullif(split_part(coalesce(d.lotes_pickeados, ''), ' / ', 1), ''), 'S/L'),
              'PACKING ' || o.numero_ov, 'REVISAR', 0, d.cantidad_pickeada - v_emp);
    end if;
  end loop;
  select coalesce(sum(cantidad_pickeada), 0) into v_total from netsuite_detalle_ov where orden_id = p_orden_id;

  -- 3) Packing list
  if p_borrador_id is not null and exists (select 1 from wms_packing_lists_fa where id = p_borrador_id and orden_id = p_orden_id) then
    update wms_packing_lists_fa set detalle_json = p_detalle, usuario_picking = v_usuario, fecha_emision = now(), bodega = o.bodega
     where id = p_borrador_id returning id into v_pl_id;
  else
    insert into wms_packing_lists_fa (orden_id, numero_ov, cliente_nombre, usuario_picking, detalle_json, fecha_emision, bodega)
    values (p_orden_id, o.numero_ov, o.cliente_nombre, v_usuario, p_detalle, now(), o.bodega)
    returning id into v_pl_id;
  end if;

  -- 4) Datos de despacho en la orden (el PC los lee de aquí)
  select string_agg(p, '|') into v_canal
  from (select btrim(p) p from unnest(string_to_array(coalesce(o.canal_venta, ''), '|')) p
        where btrim(p) <> '' and upper(btrim(p)) !~ '^(LPN|BULTOS|TIPO|COMUNA|PESO_KG|FALTANTE|MOTIVO_FALTANTE):') z;
  v_canal := concat_ws('|', nullif(v_canal, ''),
                       case when v_lpn is not null then 'LPN:' || v_lpn end,
                       'BULTOS:' || p_bultos,
                       case when nullif(btrim(p_tipo_empaque), '') is not null then 'TIPO:' || upper(btrim(p_tipo_empaque)) end,
                       case when nullif(btrim(p_comuna), '') is not null then 'COMUNA:' || upper(btrim(p_comuna)) end,
                       case when p_peso_real_kg is not null then 'PESO_KG:' || round(p_peso_real_kg, 2)
                            when p_peso_esperado_kg is not null then 'PESO_KG:' || round(p_peso_esperado_kg, 2) end,
                       case when v_faltante > 0 then 'FALTANTE:' || v_faltante end,
                       case when v_faltante > 0 then 'MOTIVO_FALTANTE:' || replace(upper(v_motivo), '|', '/') end);
  update netsuite_ordenes_venta set canal_venta = v_canal where id = p_orden_id;

  v_destino := case when upper(o.numero_ov) like 'OT-%' then 'EN_TRANSITO_CCP' else 'PENDIENTE_FACTURACION' end;
  v_estado := public.wms_cambiar_estado_ov(p_orden_id, v_destino, v_usuario,
      format('Packing %s: %s bultos, %s UN%s%s', v_modo, p_bultos, v_total,
             case when p_peso_real_kg is not null then ', ' || round(p_peso_real_kg, 2) || ' kg reales' else '' end,
             case when v_faltante > 0 then format(' · CON FALTANTE %s UN (%s): %s', v_faltante, v_motivo, rtrim(v_detalle_falt, '; ')) else '' end),
      true);
  return v_estado || jsonb_build_object('packing_list_id', v_pl_id, 'unidades', v_total, 'bultos', p_bultos, 'faltante', v_faltante);
end $$;

grant execute on function public.wms_cerrar_packing(bigint, text, jsonb, integer, text, text, text, numeric, numeric, bigint, text, text)
  to anon, authenticated, service_role;

commit;
