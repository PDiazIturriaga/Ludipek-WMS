-- =====================================================================
-- LUDIPEK WMS · 13 RECEPCIÓN DE TRASLADOS EN CONCEPCIÓN  (requiere 04, 07, 10 y 12)
-- Flujo:
--   Santiago cierra el packing de la OT-CCP en pallets con LPN  -> EN_TRANSITO_CCP
--   Concepción, en el celular: elige la OT, escanea cada pallet, revisa lote,
--   vencimiento y unidades, y lo recibe (conforme o con diferencias).
--   · Cada pallet recibido queda en el andén de Concepción (registro_recepcion)
--     listo para Almacenamiento con el mismo LPN (o uno nuevo si ese LPN ya
--     existe en Concepción).
--   · Al recibir el último pallet la OT se cierra sola:
--       RECIBIDO_CCP (todo conforme) o RECIBIDO_CCP_CON_DIFERENCIAS.
--   · Si un pallet no llegó, se cierra la OT con motivo (queda NO_LLEGO).
--   El PC (módulo Recepción CCP) revisa despachado vs recibido línea por línea.
-- Usa las tablas existentes wms_recepcion_traslados_ccp (una fila por pallet)
-- y wms_recepcion_traslados_ccp_linea (una fila por SKU/lote del pallet).
-- =====================================================================
begin;

alter table public.wms_recepcion_traslados_ccp
  add column if not exists lpn_destino text,
  add column if not exists unidades_diferencia integer not null default 0;
alter table public.wms_recepcion_traslados_ccp_linea
  add column if not exists clave text;

create index if not exists idx_rec_traslado_linea_rec on public.wms_recepcion_traslados_ccp_linea (recepcion_lpn_id);

-- ---------------------------------------------------------------------
-- Lo que salió de Santiago, por pallet y SKU/lote (desde el packing list)
-- ---------------------------------------------------------------------
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
  ), items as (
    select distinct x.value it
    from pl_src,
         jsonb_array_elements(case jsonb_typeof(pl_src.detalle_json)
                                when 'array' then pl_src.detalle_json
                                when 'string' then (pl_src.detalle_json #>> '{}')::jsonb
                                else '[]'::jsonb end) x
    where jsonb_typeof(x.value) = 'object'
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
         coalesce(max(b.descripcion), max(m.descripcion)), max(m.codigo_barras),
         b.lote, b.venc,
         greatest(coalesce(max(b.mult), max(m.multiplo), 1), 1),
         sum(b.cajas)::int, sum(b.displays)::int, sum(b.unidades)::int
  from base b left join maestra_sku m on m.sku = b.sku
  where b.lpn is not null and b.lpn <> '' and b.sku <> '' and b.unidades > 0
  group by b.lpn, b.id_detalle, b.sku, b.lote, b.venc;
$$;

-- ---------------------------------------------------------------------
-- Bandeja de traslados (celular de Concepción y PC)
-- ---------------------------------------------------------------------
create or replace function public.wms_traslados_ccp(p_solo_abiertos boolean default true)
returns table (orden_id bigint, numero_ot text, estado text, despachado_en timestamptz, despachado_por text,
               pallets integer, pallets_recibidos integer, pallets_no_llegaron integer,
               unidades_despachadas integer, unidades_recibidas integer, unidades_diferencia integer,
               pallets_con_diferencia integer, faltante_packing integer, motivo_faltante_packing text,
               recibido_por text, ultima_recepcion timestamptz)
language sql stable security definer set search_path = public as $$
  select o.id::bigint, o.numero_ov, upper(coalesce(o.estado_ns, o.estado)),
         d.cerrado_en, d.cerrado_por,
         coalesce(lp.pallets, 0), coalesce(r.recibidos, 0), coalesce(r.no_llegaron, 0),
         coalesce(lp.unidades, 0), coalesce(r.unidades_rec, 0), coalesce(r.dif, 0), coalesce(r.con_dif, 0),
         coalesce(d.faltante_un, 0), d.motivo_faltante,
         r.ultimo_usuario, r.ultima
  from netsuite_ordenes_venta o
  left join wms_despacho_ov d on d.orden_id = o.id
  left join lateral (
    select count(distinct x.lpn)::int pallets, coalesce(sum(x.unidades), 0)::int unidades
    from public.wms_traslado_lineas_despachadas(o.id) x
  ) lp on true
  left join lateral (
    select count(*) filter (where t.estado like 'RECIBIDO%')::int recibidos,
           count(*) filter (where t.estado = 'NO_LLEGO')::int no_llegaron,
           coalesce(sum(t.total_unidades_recibidas), 0)::int unidades_rec,
           coalesce(sum(t.unidades_diferencia), 0)::int dif,
           count(*) filter (where t.estado in ('RECIBIDO_CON_DIFERENCIAS', 'NO_LLEGO'))::int con_dif,
           (array_agg(t.usuario_recepcion order by t.fecha_recepcion desc nulls last))[1] ultimo_usuario,
           max(t.fecha_recepcion) ultima
    from wms_recepcion_traslados_ccp t
    where t.orden_id = o.id and (t.estado like 'RECIBIDO%' or t.estado = 'NO_LLEGO')
  ) r on true
  where upper(o.numero_ov) like 'OT-%'
    and (upper(coalesce(o.estado_ns, o.estado)) in ('EN_TRANSITO_CCP', 'RECEPCION_CCP_EN_PROCESO')
         or (not p_solo_abiertos
             and upper(coalesce(o.estado_ns, o.estado)) in ('RECIBIDO_CCP', 'RECIBIDO_CCP_CON_DIFERENCIAS')
             and coalesce(r.ultima, o.updated_at, now()) > now() - interval '90 days'))
  order by case when upper(coalesce(o.estado_ns, o.estado)) in ('EN_TRANSITO_CCP', 'RECEPCION_CCP_EN_PROCESO') then 0 else 1 end,
           coalesce(d.cerrado_en, o.updated_at) desc nulls last;
$$;

-- ---------------------------------------------------------------------
-- Detalle de una OT: pallets, líneas despachadas y lo recibido
-- ---------------------------------------------------------------------
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

-- ---------------------------------------------------------------------
-- Recibir un pallet (celular de Concepción)
--   p_lineas: [{clave, unidades_recibidas, lote_recibido?, vencimiento_recibido?}]
--             null = todo conforme. Una línea que no viene = 0 UN recibidas.
--   p_lpn_nuevo: etiqueta nueva si el LPN ya existe en Concepción.
-- ---------------------------------------------------------------------
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
    v_unid := case when p_lineas is null then x.unidades
                   else greatest(coalesce(nullif(r->>'unidades_recibidas', '')::numeric, 0), 0)::int end;
    v_lote := case when nullif(btrim(coalesce(r->>'lote_recibido', '')), '') is null then x.lote
                   else public.wms_normalizar_lote(r->>'lote_recibido') end;
    v_venc := case when nullif(btrim(coalesce(r->>'vencimiento_recibido', '')), '') is null then x.vencimiento
                   else public.wms_fecha_desde_texto(r->>'vencimiento_recibido') end;
    if nullif(btrim(coalesce(r->>'vencimiento_recibido', '')), '') is not null and upper(btrim(r->>'vencimiento_recibido')) <> 'S/F'
       and v_venc is null then
      raise exception 'WMS: vencimiento inválido "%" (SKU %). Use DD-MM-AAAA', r->>'vencimiento_recibido', x.sku;
    end if;
    v_res := case when v_unid = 0 then 'NO_LLEGO'
                  when v_unid < x.unidades then 'FALTANTE'
                  when v_unid > x.unidades then 'SOBRANTE'
                  when v_lote <> x.lote or v_venc is distinct from x.vencimiento then 'LOTE_DISTINTO'
                  else 'CONFORME' end;
    v_desp := v_desp + x.unidades;
    v_recib := v_recib + v_unid;
    v_dif := v_dif + abs(x.unidades - v_unid);
    if v_res <> 'CONFORME' then v_n_dif := v_n_dif + 1; end if;
    v_det_desp := v_det_desp || jsonb_build_object('id_detalle', x.id_detalle, 'sku', x.sku, 'descripcion', x.descripcion,
                    'lote', x.lote, 'fecha_vencimiento_cl', public.wms_fecha_cl(x.vencimiento), 'cajas', x.cajas,
                    'displays', x.displays, 'multiplo_aplicado', x.multiplo, 'unidades_totales', x.unidades);
    v_det_rec := v_det_rec || jsonb_build_object('id_detalle', x.id_detalle, 'sku', x.sku, 'lote', v_lote,
                    'fecha_vencimiento_cl', public.wms_fecha_cl(v_venc), 'unidades_totales', v_unid, 'resultado', v_res);
    v_lineas_tmp := v_lineas_tmp || jsonb_build_object('x', to_jsonb(x), 'unid', v_unid, 'lote', v_lote,
                    'venc', v_venc, 'res', v_res);
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
           usuario_recepcion, fecha_recepcion)
    values (v_rec_id, nullif(r->'x'->>'id_detalle', '')::bigint, r->'x'->>'sku', r->'x'->>'descripcion',
            r->'x'->>'lote', (r->'x'->>'vencimiento')::date, (r->'x'->>'cajas')::int, (r->'x'->>'displays')::int,
            (r->'x'->>'unidades')::int,
            r->>'lote', (r->>'venc')::date, ((r->>'unid')::int / greatest((r->'x'->>'multiplo')::int, 1)),
            (r->>'unid')::int, r->>'res', r->'x'->>'clave', case when r->>'res' <> 'CONFORME' then v_obs end, v_usuario, now());

    if (r->>'unid')::int > 0 then
      insert into registro_recepcion (lpn, documento_netsuite, sku, codigo_barras_escaneado, lote, fecha_vencimiento_cl,
             multiplo_aplicado, cajas, unidades_sueltas, unidades_totales, contenedor, bodega, operador, observaciones, fecha_recepcion)
      values (v_dest, o.numero_ov, r->'x'->>'sku', coalesce(nullif(r->'x'->>'codigo_barras', ''), r->'x'->>'sku'),
              r->>'lote', public.wms_fecha_cl((r->>'venc')::date),
              greatest((r->'x'->>'multiplo')::int, 1),
              (r->>'unid')::int / greatest((r->'x'->>'multiplo')::int, 1),
              (r->>'unid')::int % greatest((r->'x'->>'multiplo')::int, 1),
              (r->>'unid')::int, o.numero_ov, v_bodega, v_usuario,
              'Traslado ' || o.numero_ov || case when v_dest <> v_lpn then ' · LPN origen ' || v_lpn else '' end, now());
      perform public.wms_kardex(v_bodega, 'RECEPCION_TRASLADO (' || o.numero_ov || ')', v_dest, r->'x'->>'sku', r->>'lote',
              'TRANSITO ' || v_lpn, 'ANDEN_TRANSITO',
              (r->>'unid')::int / greatest((r->'x'->>'multiplo')::int, 1), (r->>'unid')::int);
    end if;
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

-- ---------------------------------------------------------------------
-- Cerrar la recepción de una OT. Los pallets pendientes quedan NO_LLEGO
-- (exige motivo). Estado final: RECIBIDO_CCP o RECIBIDO_CCP_CON_DIFERENCIAS.
-- ---------------------------------------------------------------------
create or replace function public.wms_cerrar_recepcion_traslado(
  p_orden_id bigint, p_usuario text default null, p_motivo text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o record;
  p record;
  v_usuario text := public.wms_contexto(p_usuario, 'wms_cerrar_recepcion_traslado');
  v_motivo text := nullif(btrim(coalesce(p_motivo, '')), '');
  v_estado text;
  v_no_llego int := 0;
  v_con_dif int;
  v_recibidos int;
  v_res jsonb;
begin
  select * into o from netsuite_ordenes_venta where id = p_orden_id for update;
  if not found then raise exception 'WMS: la orden % no existe', p_orden_id; end if;
  v_estado := upper(coalesce(o.estado_ns, o.estado));
  if v_estado not in ('EN_TRANSITO_CCP', 'RECEPCION_CCP_EN_PROCESO') then
    raise exception 'WMS: la OT % está % y no se puede cerrar', o.numero_ov, v_estado;
  end if;

  for p in
    select d.lpn, sum(d.unidades)::int unidades, sum(d.cajas)::int cajas, sum(d.displays)::int displays,
           jsonb_agg(jsonb_build_object('id_detalle', d.id_detalle, 'sku', d.sku, 'descripcion', d.descripcion, 'lote', d.lote,
                     'fecha_vencimiento_cl', public.wms_fecha_cl(d.vencimiento), 'cajas', d.cajas, 'displays', d.displays,
                     'multiplo_aplicado', d.multiplo, 'unidades_totales', d.unidades)) det,
           jsonb_agg(jsonb_build_object('sku', d.sku, 'lote', d.lote, 'unidades', d.unidades)) kdx
    from public.wms_traslado_lineas_despachadas(p_orden_id) d
    where not exists (select 1 from wms_recepcion_traslados_ccp t
                      where t.orden_id = p_orden_id and upper(t.lpn) = d.lpn
                        and t.estado in ('RECIBIDO_CCP', 'RECIBIDO_CON_DIFERENCIAS', 'NO_LLEGO'))
    group by d.lpn
  loop
    if v_motivo is null then
      raise exception 'WMS: hay pallets sin recibir (%). Indique el motivo para cerrar la OT.', p.lpn;
    end if;
    insert into wms_recepcion_traslados_ccp (orden_id, numero_ot, lpn, bodega_origen, bodega_destino, estado,
           detalle_despachado, detalle_recibido, total_cajas_despachadas, total_displays_despachados,
           total_unidades_despachadas, total_unidades_recibidas, unidades_diferencia,
           usuario_recepcion, fecha_recepcion, observacion, updated_at)
    values (o.id, o.numero_ov, p.lpn, 'Bodega Santiago', 'Bodega Concepcion', 'NO_LLEGO', p.det, '[]'::jsonb,
            p.cajas, p.displays, p.unidades, 0, p.unidades, v_usuario, now(), v_motivo, now())
    on conflict (numero_ot, lpn) do update set
      estado = 'NO_LLEGO', detalle_despachado = excluded.detalle_despachado, detalle_recibido = '[]'::jsonb,
      total_unidades_despachadas = excluded.total_unidades_despachadas, total_unidades_recibidas = 0,
      unidades_diferencia = excluded.unidades_diferencia, usuario_recepcion = excluded.usuario_recepcion,
      fecha_recepcion = now(), observacion = excluded.observacion, updated_at = now();
    insert into historial_movimientos (bodega, usuario, tipo_movimiento, lpn, sku, lote, ubicacion_origen, ubicacion_destino,
                                       cajas_afectadas, unidades_afectadas)
    select 'Bodega Concepcion', v_usuario, 'DIFERENCIA_TRASLADO (' || o.numero_ov || ')', p.lpn, k->>'sku', k->>'lote',
           'DESPACHADO ' || (k->>'unidades'), 'PALLET NO LLEGÓ', 0, (k->>'unidades')::int
    from jsonb_array_elements(p.kdx) k;
    v_no_llego := v_no_llego + 1;
  end loop;

  select count(*) filter (where estado in ('RECIBIDO_CON_DIFERENCIAS', 'NO_LLEGO')), count(*) filter (where estado like 'RECIBIDO%')
    into v_con_dif, v_recibidos
  from wms_recepcion_traslados_ccp where orden_id = p_orden_id;
  if v_recibidos = 0 and v_no_llego = 0 then
    raise exception 'WMS: la OT % no tiene pallets recibidos', o.numero_ov;
  end if;

  v_res := public.wms_cambiar_estado_ov(o.id,
             case when v_con_dif > 0 then 'RECIBIDO_CCP_CON_DIFERENCIAS' else 'RECIBIDO_CCP' end,
             v_usuario,
             format('Recepción en Concepción cerrada: %s pallet(s) recibidos%s%s', v_recibidos,
                    case when v_no_llego > 0 then format(', %s no llegaron', v_no_llego) else '' end,
                    coalesce(' · ' || v_motivo, '')));
  return v_res || jsonb_build_object('pallets_recibidos', v_recibidos, 'pallets_no_llegaron', v_no_llego);
end $$;

grant execute on function public.wms_traslado_lineas_despachadas(bigint) to anon, authenticated, service_role;
grant execute on function public.wms_traslados_ccp(boolean) to anon, authenticated, service_role;
grant execute on function public.wms_traslado_ccp_detalle(bigint) to anon, authenticated, service_role;
grant execute on function public.wms_recibir_pallet_traslado(bigint, text, jsonb, text, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_cerrar_recepcion_traslado(bigint, text, text) to anon, authenticated, service_role;

commit;
