-- =====================================================================
-- LUDIPEK WMS · 39 RECEPCIÓN EN CONCEPCIÓN Y VACÍAS DE PICKING  (requiere 13, 30 y 35)
--
-- 1) Cantidades al doble/triple en Concepción: cada guardado del packing (borradores y cierre)
--    repetía los pallets ya cerrados en wms_packing_lists_fa y se sumaban todos. Ahora, por cada
--    pallet, solo cuenta el packing list más reciente que lo contiene.
-- 2) Escanear el DISPLAY en Concepción: la línea acepta el código de la caja y el del display
--    (SKU-FA). El celular además reconoce caja y display del mismo GTIN.
-- 3) Varios lotes en una misma línea: si Santiago mandó cajas de otro lote o fecha, Concepción
--    registra cada lote con sus unidades ("+ OTRO LOTE"). Cada lote queda como stock aparte en
--    el andén de Concepción y la línea queda LOTE_DISTINTO con el detalle.
-- 4) Ubicaciones de picking vacías: ya no entran en las tareas de "Ubicaciones vacías" (no son
--    espacio para pallets). Quedan como dato en Salud del sistema.
-- =====================================================================
begin;

alter table public.wms_recepcion_traslados_ccp_linea add column if not exists partes_recibidas jsonb;

create or replace function public.wms_traslado_lineas_despachadas(p_orden_id bigint)
returns table (clave text, lpn text, id_detalle bigint, sku text, descripcion text, codigo_barras text,
               lote text, vencimiento date, multiplo integer, cajas integer, displays integer, unidades integer)
language sql stable security definer set search_path = public as $$
  with o as (
    select id, upper(numero_ov) numero_ov from netsuite_ordenes_venta where id = p_orden_id
  ), pl_oficial as (
    select pl.id, pl.detalle_json
    from wms_despacho_ov d join wms_packing_lists_fa pl on pl.id = d.packing_list_id
    where d.orden_id = p_orden_id
  ), pl_src as (
    select * from pl_oficial
    union all
    select pl.id, pl.detalle_json
    from wms_packing_lists_fa pl, o
    where not exists (select 1 from pl_oficial)
      and (pl.orden_id = o.id or upper(pl.numero_ov) = o.numero_ov)
  ), items_todos as (
    -- Cada guardado del packing (borradores y cierre) repite los pallets ya cerrados: antes se
    -- sumaban todos y las cantidades salían al doble o al triple. Ahora, por cada pallet, solo
    -- cuenta el packing list más reciente que lo contiene.
    select pl_src.id plid, x.value it, x.n,
           upper(btrim(coalesce(nullif(x.value->>'lpn_pallet', ''), nullif(x.value->>'lpn_consolidado', '')))) lpn_it
    from pl_src,
         jsonb_array_elements(case jsonb_typeof(pl_src.detalle_json)
                                when 'array' then pl_src.detalle_json
                                when 'string' then (pl_src.detalle_json #>> '{}')::jsonb
                                else '[]'::jsonb end) with ordinality x(value, n)
    where jsonb_typeof(x.value) = 'object'
  ), items as (
    select it from (select i.*, max(i.plid) over (partition by i.lpn_it) plid_max from items_todos i) z
    where z.plid = z.plid_max
  ), base as (
    select
      upper(btrim(coalesce(nullif(it->>'lpn_pallet', ''), nullif(it->>'lpn_consolidado', '')))) lpn,
      nullif(it->>'id_detalle', '')::bigint id_detalle,
      public.wms_normalizar_sku(it->>'sku') sku,
      nullif(it->>'descripcion', '') descripcion,
      public.wms_normalizar_lote(coalesce(nullif(btrim(it->>'lote'), ''),
          nullif(btrim(split_part(regexp_replace(coalesce(it->>'lotes', ''), '^\[[^]]*\]\s*', ''), ' / ', 1)), ''))) lote,
      public.wms_fecha_desde_texto(coalesce(nullif(btrim(it->>'fecha_vencimiento_cl'), ''),
          nullif(btrim(split_part(split_part(regexp_replace(coalesce(it->>'lotes', ''), '^\[[^]]*\]\s*', ''), ' / ', 2), '(', 1)), ''))) venc,
      nullif(coalesce(it->>'multiplo_aplicado', it->>'multiplo'), '')::numeric::int mult,
      coalesce(nullif(it->>'cajas', '')::numeric, 0)::int cajas,
      coalesce(nullif(it->>'displays', '')::numeric, 0)::int displays,
      coalesce(nullif(it->>'unidades_totales', '')::numeric, nullif(it->>'pickeado', '')::numeric, 0)::int unidades
    from items
  )
  select concat_ws('|', b.lpn, coalesce(b.id_detalle::text, ''), b.sku, b.lote, coalesce(to_char(b.venc, 'YYYY-MM-DD'), '')),
         b.lpn, b.id_detalle, b.sku,
         coalesce(max(b.descripcion), max(m.descripcion)),
         -- códigos de la caja y del display (SKU-FA): en Concepción se puede escanear cualquiera
         (select string_agg(distinct btrim(m2.codigo_barras), ',') from maestra_sku m2
           where upper(m2.sku) in (b.sku, b.sku || '-FA') and coalesce(btrim(m2.codigo_barras), '') <> ''),
         b.lote, b.venc,
         greatest(coalesce(max(b.mult), max(m.multiplo), 1), 1),
         sum(b.cajas)::int, sum(b.displays)::int, sum(b.unidades)::int
  from base b left join maestra_sku m on m.sku = b.sku
  where b.lpn is not null and b.lpn <> '' and b.sku <> '' and b.unidades > 0
  group by b.lpn, b.id_detalle, b.sku, b.lote, b.venc;
$$;

create or replace function public.wms_traslado_ccp_detalle(p_orden_id bigint)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare
  o record;
  v_pallets jsonb;
begin
  select * into o from netsuite_ordenes_venta where id = p_orden_id;
  if not found then raise exception 'WMS: la orden % no existe', p_orden_id; end if;

  select coalesce(jsonb_agg(p order by (p->>'pendiente')::boolean desc, p->>'lpn'), '[]'::jsonb) into v_pallets
  from (
    select jsonb_build_object(
      'lpn', x.lpn,
      'estado', coalesce(t.estado, 'PENDIENTE'),
      'pendiente', t.id is null or t.estado not in ('RECIBIDO_CCP', 'RECIBIDO_CON_DIFERENCIAS', 'NO_LLEGO'),
      'lpn_destino', t.lpn_destino,
      'usuario', t.usuario_recepcion,
      'fecha', t.fecha_recepcion,
      'observacion', t.observacion,
      'unidades_despachadas', sum(x.unidades),
      'unidades_recibidas', coalesce(max(t.total_unidades_recibidas), 0),
      'skus', count(distinct x.sku),
      'lineas', jsonb_agg(jsonb_build_object(
          'clave', x.clave, 'id_detalle', x.id_detalle, 'sku', x.sku, 'descripcion', x.descripcion,
          'codigo_barras', x.codigo_barras, 'lote', x.lote,
          'vencimiento', public.wms_fecha_cl(x.vencimiento),
          'multiplo', x.multiplo, 'cajas', x.cajas, 'displays', x.displays, 'unidades', x.unidades,
          'lote_recibido', l.lote_recibido, 'vencimiento_recibido', public.wms_fecha_cl(l.vencimiento_recibido),
          'unidades_recibidas', l.unidades_recibidas, 'resultado', coalesce(l.resultado, 'PENDIENTE'),
          'partes', l.partes_recibidas,
          'observacion', l.observacion)
        order by x.sku, x.lote)) p
    from public.wms_traslado_lineas_despachadas(p_orden_id) x
    left join wms_recepcion_traslados_ccp t on t.orden_id = p_orden_id and upper(t.lpn) = x.lpn
    left join wms_recepcion_traslados_ccp_linea l on l.recepcion_lpn_id = t.id and l.clave = x.clave
    group by x.lpn, t.id, t.estado, t.lpn_destino, t.usuario_recepcion, t.fecha_recepcion, t.observacion
  ) z(p);

  return jsonb_build_object(
    'orden_id', o.id, 'numero_ot', o.numero_ov, 'estado', upper(coalesce(o.estado_ns, o.estado)),
    'despacho', (select to_jsonb(d) - 'orden_id' from wms_despacho_ov d where d.orden_id = o.id),
    'pallets', v_pallets);
end $$;

create or replace function public.wms_recibir_pallet_traslado(
  p_orden_id bigint, p_lpn text, p_lineas jsonb default null, p_usuario text default null,
  p_observacion text default null, p_lpn_nuevo text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o record;
  x record;
  v_bodega constant text := 'Bodega Concepcion';
  v_usuario text := public.wms_contexto(p_usuario, 'wms_recibir_pallet_traslado');
  v_lpn text := upper(btrim(coalesce(p_lpn, '')));
  v_dest text := coalesce(nullif(upper(btrim(coalesce(p_lpn_nuevo, ''))), ''), upper(btrim(coalesce(p_lpn, ''))));
  v_obs text := nullif(btrim(coalesce(p_observacion, '')), '');
  v_estado_ot text;
  v_rec_id bigint;
  v_ant record;
  r jsonb;
  v_unid int; v_lote text; v_venc date; v_res text;
  v_desp int := 0; v_recib int := 0; v_dif int := 0; v_n_dif int := 0;
  v_det_desp jsonb := '[]'::jsonb; v_det_rec jsonb := '[]'::jsonb;
  v_lineas_tmp jsonb := '[]'::jsonb;
  v_pend int;
  v_cierre jsonb;
  v_partes jsonb;
  pr record;
  r2 jsonb;
begin
  select * into o from netsuite_ordenes_venta where id = p_orden_id for update;
  if not found then raise exception 'WMS: la orden % no existe', p_orden_id; end if;
  if upper(o.numero_ov) not like 'OT-%' then raise exception 'WMS: % no es un traslado (OT)', o.numero_ov; end if;
  v_estado_ot := upper(coalesce(o.estado_ns, o.estado));
  if v_estado_ot not in ('EN_TRANSITO_CCP', 'RECEPCION_CCP_EN_PROCESO') then
    raise exception 'WMS: la OT % está % y no se puede recibir', o.numero_ov, v_estado_ot;
  end if;
  if v_lpn = '' then raise exception 'WMS: escanee el LPN del pallet'; end if;
  if v_lpn ~ '^\d{18}$' then v_lpn := 'SSCC-' || v_lpn; end if;
  if v_dest ~ '^\d{18}$' then v_dest := 'SSCC-' || v_dest; end if;
  if not exists (select 1 from public.wms_traslado_lineas_despachadas(p_orden_id) d where d.lpn = v_lpn) then
    raise exception 'WMS: el LPN % no viene en la OT %. Revise la etiqueta.', v_lpn, o.numero_ov;
  end if;

  perform pg_advisory_xact_lock(hashtext('LPN|' || v_dest));
  select * into v_ant from wms_recepcion_traslados_ccp where numero_ot = o.numero_ov and upper(lpn) = v_lpn;
  if found and v_ant.estado in ('RECIBIDO_CCP', 'RECIBIDO_CON_DIFERENCIAS') then
    raise exception 'WMS: el pallet % ya fue recibido por % el %', v_lpn, coalesce(v_ant.usuario_recepcion, '?'),
      to_char(v_ant.fecha_recepcion at time zone 'America/Santiago', 'DD-MM-YYYY HH24:MI');
  end if;

  -- El LPN con que queda en Concepción no puede existir ya en Concepción
  if exists (select 1 from registro_recepcion where bodega = v_bodega and upper(lpn) = v_dest)
     or exists (select 1 from bodega_inventario_ubicacion where bodega = v_bodega and upper(lpn) = v_dest)
     or exists (select 1 from historial_movimientos where bodega = v_bodega and upper(lpn) = v_dest) then
    raise exception 'WMS: LPN_EN_USO_CCP: el LPN % ya existe en Concepción. Pegue una etiqueta nueva sobre el pallet y escanéela.', v_dest;
  end if;
  if v_dest <> v_lpn and exists (select 1 from public.wms_traslado_lineas_despachadas(p_orden_id) d where d.lpn = v_dest) then
    raise exception 'WMS: el LPN % es otro pallet de esta OT; use una etiqueta nueva', v_dest;
  end if;

  -- Comparar línea por línea
  for x in select * from public.wms_traslado_lineas_despachadas(p_orden_id) d where d.lpn = v_lpn order by d.sku, d.lote loop
    if p_lineas is null then
      r := null;
    else
      select e into r from jsonb_array_elements(p_lineas) e where e->>'clave' = x.clave limit 1;
    end if;
    -- Varios lotes en la misma línea (Santiago mandó cajas de otro lote/fecha): 'partes'
    v_partes := null;
    if r is not null and jsonb_typeof(r->'partes') = 'array' and jsonb_array_length(r->'partes') > 0 then
      select jsonb_agg(jsonb_build_object(
               'lote', coalesce(nullif(public.wms_normalizar_lote(p->>'lote'), ''), x.lote),
               'venc', coalesce(public.wms_fecha_desde_texto(nullif(btrim(coalesce(p->>'vencimiento', '')), '')), x.vencimiento),
               'unid', greatest(coalesce(nullif(p->>'unidades', '')::numeric, 0), 0)::int))
        into v_partes
        from jsonb_array_elements(r->'partes') p
       where coalesce(nullif(p->>'unidades', '')::numeric, 0) > 0;
    end if;
    if v_partes is not null then
      v_unid := (select sum((p->>'unid')::int) from jsonb_array_elements(v_partes) p);
      v_lote := v_partes->0->>'lote';
      v_venc := (v_partes->0->>'venc')::date;
    else
    v_unid := case when p_lineas is null then x.unidades
                   else greatest(coalesce(nullif(r->>'unidades_recibidas', '')::numeric, 0), 0)::int end;
    v_lote := case when nullif(btrim(coalesce(r->>'lote_recibido', '')), '') is null then x.lote
                   else public.wms_normalizar_lote(r->>'lote_recibido') end;
    v_venc := case when nullif(btrim(coalesce(r->>'vencimiento_recibido', '')), '') is null then x.vencimiento
                   else public.wms_fecha_desde_texto(r->>'vencimiento_recibido') end;
      v_partes := jsonb_build_array(jsonb_build_object('lote', v_lote, 'venc', v_venc, 'unid', v_unid));
    end if;
    if nullif(btrim(coalesce(r->>'vencimiento_recibido', '')), '') is not null and upper(btrim(r->>'vencimiento_recibido')) <> 'S/F'
       and v_venc is null then
      raise exception 'WMS: vencimiento inválido "%" (SKU %). Use DD-MM-AAAA', r->>'vencimiento_recibido', x.sku;
    end if;
    v_res := case when v_unid = 0 then 'NO_LLEGO'
                  when v_unid < x.unidades then 'FALTANTE'
                  when v_unid > x.unidades then 'SOBRANTE'
                  when exists (select 1 from jsonb_array_elements(v_partes) p
                                where (p->>'lote') <> x.lote or (p->>'venc')::date is distinct from x.vencimiento) then 'LOTE_DISTINTO'
                  else 'CONFORME' end;
    v_desp := v_desp + x.unidades;
    v_recib := v_recib + v_unid;
    v_dif := v_dif + abs(x.unidades - v_unid);
    if v_res <> 'CONFORME' then v_n_dif := v_n_dif + 1; end if;
    v_det_desp := v_det_desp || jsonb_build_object('id_detalle', x.id_detalle, 'sku', x.sku, 'descripcion', x.descripcion,
                    'lote', x.lote, 'fecha_vencimiento_cl', public.wms_fecha_cl(x.vencimiento), 'cajas', x.cajas,
                    'displays', x.displays, 'multiplo_aplicado', x.multiplo, 'unidades_totales', x.unidades);
    v_det_rec := v_det_rec || (select jsonb_agg(jsonb_build_object('id_detalle', x.id_detalle, 'sku', x.sku, 'lote', p->>'lote',
                    'fecha_vencimiento_cl', public.wms_fecha_cl((p->>'venc')::date), 'unidades_totales', (p->>'unid')::int,
                    'resultado', v_res)) from jsonb_array_elements(v_partes) p);
    v_lineas_tmp := v_lineas_tmp || jsonb_build_object('x', to_jsonb(x), 'unid', v_unid, 'lote', v_lote,
                    'venc', v_venc, 'res', v_res, 'partes', v_partes);
  end loop;

  if v_recib = 0 then
    raise exception 'WMS: no se registró ninguna unidad. Si el pallet no llegó, ciérrelo desde "Pallets que no llegaron".';
  end if;
  if v_n_dif > 0 and v_obs is null then
    raise exception 'WMS: hay % línea(s) con diferencia. Indique el motivo para recibir con diferencias.', v_n_dif;
  end if;

  -- Cabecera del pallet
  insert into wms_recepcion_traslados_ccp (orden_id, numero_ot, lpn, lpn_destino, bodega_origen, bodega_destino, estado,
         detalle_despachado, detalle_recibido, total_cajas_despachadas, total_displays_despachados,
         total_unidades_despachadas, total_unidades_recibidas, unidades_diferencia,
         usuario_recepcion, fecha_recepcion, observacion, updated_at)
  values (o.id, o.numero_ov, v_lpn, v_dest, 'Bodega Santiago', v_bodega,
          case when v_n_dif > 0 then 'RECIBIDO_CON_DIFERENCIAS' else 'RECIBIDO_CCP' end,
          v_det_desp, v_det_rec,
          (select coalesce(sum((e->>'cajas')::int), 0) from jsonb_array_elements(v_det_desp) e),
          (select coalesce(sum((e->>'displays')::int), 0) from jsonb_array_elements(v_det_desp) e),
          v_desp, v_recib, v_dif, v_usuario, now(), v_obs, now())
  on conflict (numero_ot, lpn) do update set
    orden_id = excluded.orden_id, lpn_destino = excluded.lpn_destino, estado = excluded.estado,
    detalle_despachado = excluded.detalle_despachado, detalle_recibido = excluded.detalle_recibido,
    total_cajas_despachadas = excluded.total_cajas_despachadas, total_displays_despachados = excluded.total_displays_despachados,
    total_unidades_despachadas = excluded.total_unidades_despachadas, total_unidades_recibidas = excluded.total_unidades_recibidas,
    unidades_diferencia = excluded.unidades_diferencia, usuario_recepcion = excluded.usuario_recepcion,
    fecha_recepcion = excluded.fecha_recepcion, observacion = excluded.observacion, updated_at = now()
  returning id into v_rec_id;

  delete from wms_recepcion_traslados_ccp_linea where recepcion_lpn_id = v_rec_id;

  -- Líneas: detalle, andén de Concepción y kardex
  for r in select * from jsonb_array_elements(v_lineas_tmp) loop
    insert into wms_recepcion_traslados_ccp_linea (recepcion_lpn_id, detalle_orden_id, sku, descripcion,
           lote_despachado, vencimiento_despachado, cajas_despachadas, displays_despachados, unidades_despachadas,
           lote_recibido, vencimiento_recibido, cajas_recibidas, unidades_recibidas, resultado, clave, observacion,
           usuario_recepcion, fecha_recepcion, partes_recibidas)
    values (v_rec_id, nullif(r->'x'->>'id_detalle', '')::bigint, r->'x'->>'sku', r->'x'->>'descripcion',
            r->'x'->>'lote', (r->'x'->>'vencimiento')::date, (r->'x'->>'cajas')::int, (r->'x'->>'displays')::int,
            (r->'x'->>'unidades')::int,
            r->>'lote', (r->>'venc')::date, ((r->>'unid')::int / greatest((r->'x'->>'multiplo')::int, 1)),
            (r->>'unid')::int, r->>'res', r->'x'->>'clave', case when r->>'res' <> 'CONFORME' then v_obs end, v_usuario, now(),
            case when jsonb_array_length(r->'partes') > 1 then
              (select jsonb_agg(jsonb_build_object('lote', p->>'lote', 'vencimiento', public.wms_fecha_cl((p->>'venc')::date),
                                                   'unidades', (p->>'unid')::int)) from jsonb_array_elements(r->'partes') p) end);

    -- Stock en el andén de Concepción: una fila por lote recibido
    for pr in select p from jsonb_array_elements(r->'partes') p where (p->>'unid')::int > 0 loop
      r2 := r || jsonb_build_object('unid', (pr.p->>'unid')::int, 'lote', pr.p->>'lote', 'venc', pr.p->>'venc');
    if (r2->>'unid')::int > 0 then
      insert into registro_recepcion (lpn, documento_netsuite, sku, codigo_barras_escaneado, lote, fecha_vencimiento_cl,
             multiplo_aplicado, cajas, unidades_sueltas, unidades_totales, contenedor, bodega, operador, observaciones, fecha_recepcion)
      values (v_dest, o.numero_ov, r2->'x'->>'sku', coalesce(nullif(split_part(r2->'x'->>'codigo_barras', ',', 1), ''), r2->'x'->>'sku'),
              r2->>'lote', public.wms_fecha_cl((r2->>'venc')::date),
              greatest((r2->'x'->>'multiplo')::int, 1),
              (r2->>'unid')::int / greatest((r2->'x'->>'multiplo')::int, 1),
              (r2->>'unid')::int % greatest((r2->'x'->>'multiplo')::int, 1),
              (r2->>'unid')::int, o.numero_ov, v_bodega, v_usuario,
              'Traslado ' || o.numero_ov || case when v_dest <> v_lpn then ' · LPN origen ' || v_lpn else '' end, now());
      perform public.wms_kardex(v_bodega, 'RECEPCION_TRASLADO (' || o.numero_ov || ')', v_dest, r2->'x'->>'sku', r2->>'lote',
              'TRANSITO ' || v_lpn, 'ANDEN_TRANSITO',
              (r2->>'unid')::int / greatest((r2->'x'->>'multiplo')::int, 1), (r2->>'unid')::int);
    end if;
    end loop;
    if (r->>'res') in ('FALTANTE', 'NO_LLEGO', 'SOBRANTE') then
      perform public.wms_kardex(v_bodega, 'DIFERENCIA_TRASLADO (' || o.numero_ov || ')', v_dest, r->'x'->>'sku', r->'x'->>'lote',
              'DESPACHADO ' || (r->'x'->>'unidades'), 'RECIBIDO ' || (r->>'unid'), 0,
              abs((r->'x'->>'unidades')::int - (r->>'unid')::int));
    end if;
  end loop;

  if v_estado_ot = 'EN_TRANSITO_CCP' then
    perform public.wms_cambiar_estado_ov(o.id, 'RECEPCION_CCP_EN_PROCESO', v_usuario,
              'Concepción comenzó a recibir (pallet ' || v_lpn || ')');
  end if;

  -- ¿Quedan pallets? Si no, la OT se cierra sola
  select count(distinct d.lpn) into v_pend
  from public.wms_traslado_lineas_despachadas(p_orden_id) d
  where not exists (select 1 from wms_recepcion_traslados_ccp t
                    where t.orden_id = p_orden_id and upper(t.lpn) = d.lpn
                      and t.estado in ('RECIBIDO_CCP', 'RECIBIDO_CON_DIFERENCIAS', 'NO_LLEGO'));
  if v_pend = 0 then
    v_cierre := public.wms_cerrar_recepcion_traslado(p_orden_id, v_usuario, null);
  end if;

  return jsonb_build_object('numero_ot', o.numero_ov, 'lpn', v_lpn, 'lpn_destino', v_dest,
    'resultado', case when v_n_dif > 0 then 'RECIBIDO_CON_DIFERENCIAS' else 'RECIBIDO_CCP' end,
    'unidades_despachadas', v_desp, 'unidades_recibidas', v_recib, 'lineas_con_diferencia', v_n_dif,
    'pallets_pendientes', v_pend,
    'estado_ot', coalesce(v_cierre->>'estado_nuevo', 'RECEPCION_CCP_EN_PROCESO'));
end $$;

grant execute on function public.wms_traslado_lineas_despachadas(bigint) to anon, authenticated, service_role;
grant execute on function public.wms_traslado_ccp_detalle(bigint) to anon, authenticated, service_role;

-- 4) Vacías sin las ubicaciones de picking
create or replace function public.wms_vacias_de_tarea(p_bodega text, p_pasillo text, p_desde timestamptz)
returns table (ub text) language sql stable security definer set search_path = public as $$
  select upper(u.codigo_ubicacion)
  from bodega_ubicaciones u
  where u.bodega = p_bodega and upper(u.codigo_ubicacion) like upper(p_pasillo) || '-%'
    and not public.wms_es_ubicacion_picking(u.codigo_ubicacion)
    and not exists (select 1 from bodega_inventario_ubicacion i
                    where i.bodega = u.bodega and upper(i.codigo_ubicacion) = upper(u.codigo_ubicacion)
                      and i.cantidad_unidades > 0)
    and not exists (select 1 from historial_movimientos h
                    where h.tipo_movimiento = 'ALERTA_VACIA_OCUPADA'
                      and upper(h.ubicacion_destino) = upper(u.codigo_ubicacion)
                      and coalesce(h.bodega, p_bodega) = p_bodega
                      and public.wms_ts_app(h.fecha) < p_desde);
$$;

commit;

-- Revisión: unidades por pallet de las OT en tránsito (deben cuadrar con la etiqueta del pallet)
select o.numero_ov, d.lpn, count(*) lineas, sum(d.unidades) unidades
  from public.netsuite_ordenes_venta o, lateral public.wms_traslado_lineas_despachadas(o.id) d
 where upper(coalesce(o.estado_ns, o.estado)) in ('EN_TRANSITO_CCP', 'RECEPCION_CCP_EN_PROCESO')
 group by 1, 2 order by 1, 2;
