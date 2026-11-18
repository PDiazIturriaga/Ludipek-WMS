-- =====================================================================
-- LUDIPEK WMS · 04 FUNCIONES DE OPERACIÓN (RPC)  (FASE A · requiere 01-03)
-- Cada operación física es UNA transacción en el servidor:
--   · todo o nada (si falla a mitad, no queda stock a medias)
--   · bloquea las filas que toca (dos operadores no pueden descontar el
--     mismo stock ni usar el mismo LPN al mismo tiempo)
--   · valida reglas de negocio y escribe el kardex automáticamente.
-- Las apps las llaman con supabase.rpc('wms_...', params).
-- =====================================================================
begin;

-- ---------------------------------------------------------------------
-- Utilidades internas
-- ---------------------------------------------------------------------
create or replace function public.wms_bodega_valida(p text)
returns text language plpgsql immutable as $$
declare
  t text := upper(translate(btrim(coalesce(p, '')), 'ÓóÉéÍíÁáÚú', 'OoEeIiAaUu'));
begin
  if t like '%CONCEPCION%' then return 'Bodega Concepcion'; end if;
  if t like '%SANTIAGO%' or t = '' then return 'Bodega Santiago'; end if;
  raise exception 'WMS: bodega desconocida "%"', p;
end $$;

create or replace function public.wms_normalizar_ubicacion(p text)
returns text language sql immutable as $$
  select regexp_replace(
           regexp_replace(
             regexp_replace(upper(btrim(coalesce(p, ''))), '^RACK\s*', ''),
             '\s+', '-', 'g'),
           '-+', '-', 'g');
$$;

create or replace function public.wms_contexto(p_usuario text, p_origen text)
returns text language plpgsql as $$
declare
  v_usuario text := coalesce(nullif(upper(btrim(p_usuario)), ''), 'APP');
begin
  perform set_config('wms.usuario', v_usuario, true);
  perform set_config('wms.origen', p_origen, true);
  return v_usuario;
end $$;

-- Devuelve la ubicación validada. ZONA-PICKING / ZONA-MERMA se crean solas.
create or replace function public.wms_ubicacion_valida(p_bodega text, p_codigo text)
returns text language plpgsql as $$
declare
  v_cod text := public.wms_normalizar_ubicacion(p_codigo);
  u record;
begin
  if v_cod = '' then
    raise exception 'WMS: debe indicar una ubicación';
  end if;
  if v_cod in ('ZONA-PICKING', 'ZONA-MERMA') then
    insert into public.bodega_ubicaciones (codigo_ubicacion, zona, bodega, tipo_ubicacion, estado)
    values (v_cod, split_part(v_cod, '-', 2), p_bodega, 'ZONA_ESPECIAL', 'Habilitada')
    on conflict (bodega, codigo_ubicacion) do nothing;
    return v_cod;
  end if;
  select * into u from public.bodega_ubicaciones
   where bodega = p_bodega and upper(codigo_ubicacion) = v_cod;
  if not found then
    raise exception 'WMS: la ubicación % no existe en la maestra de %', v_cod, p_bodega;
  end if;
  if coalesce(u.estado, '') ilike 'deshabilit%' or coalesce(u.estado, '') ilike 'bloque%'
     or coalesce(u.estado_ubicacion, '') ilike 'bloque%' then
    raise exception 'WMS: la ubicación % está bloqueada (%)', v_cod, coalesce(u.bloqueada_motivo, u.estado);
  end if;
  return u.codigo_ubicacion;
end $$;

create or replace function public.wms_kardex(
  p_bodega text, p_tipo text, p_lpn text, p_sku text, p_lote text,
  p_origen text, p_destino text, p_cajas integer, p_unidades integer)
returns void language sql as $$
  insert into public.historial_movimientos
    (bodega, usuario, tipo_movimiento, lpn, sku, lote, ubicacion_origen, ubicacion_destino, cajas_afectadas, unidades_afectadas)
  values (p_bodega, current_setting('wms.usuario', true), p_tipo, p_lpn, p_sku, coalesce(p_lote, 'S/L'),
          p_origen, p_destino, coalesce(p_cajas, 0), coalesce(p_unidades, 0));
$$;

-- Suma stock en una ubicación (fusiona con la fila existente del mismo SKU/lote/LPN)
create or replace function public.wms_sumar_en_ubicacion(
  p_bodega text, p_ubicacion text, p_sku text, p_lote text, p_lpn text,
  p_venc_cl text, p_cajas integer, p_unidades integer)
returns bigint language plpgsql as $$
declare
  v_id bigint;
  v_lote text := public.wms_normalizar_lote(p_lote);
  v_lpn  text := nullif(upper(btrim(coalesce(p_lpn, ''))), '');
begin
  if coalesce(p_unidades, 0) <= 0 then
    return null;
  end if;
  perform pg_advisory_xact_lock(hashtext('INV|' || p_bodega || '|' || p_ubicacion || '|' || p_sku || '|' || v_lote || '|' || coalesce(v_lpn, '')));
  select id into v_id from public.bodega_inventario_ubicacion
   where bodega = p_bodega and codigo_ubicacion = p_ubicacion and sku = p_sku and lote = v_lote
     and lpn is not distinct from v_lpn
   order by id limit 1 for update;
  if found then
    update public.bodega_inventario_ubicacion
       set cantidad_unidades = cantidad_unidades + p_unidades,
           cajas = coalesce(cajas, 0) + coalesce(p_cajas, 0),
           fecha_vencimiento_cl = coalesce(fecha_vencimiento_cl, p_venc_cl),
           auditor = current_setting('wms.usuario', true),
           fecha = now()::text
     where id = v_id;
  else
    insert into public.bodega_inventario_ubicacion
      (bodega, codigo_ubicacion, sku, lote, lpn, fecha_vencimiento_cl, cajas, cantidad_unidades, auditor, fecha)
    values (p_bodega, p_ubicacion, p_sku, v_lote, v_lpn, p_venc_cl, coalesce(p_cajas, 0), p_unidades,
            current_setting('wms.usuario', true), now()::text)
    returning id into v_id;
  end if;
  return v_id;
end $$;

-- =====================================================================
-- 1. RECEPCIÓN: cerrar pallet (LPN) con sus líneas
--    p_lineas: [{"sku","lote","fecha_vencimiento","cajas","multiplo",
--                "unidades_sueltas","unidades_totales","codigo_barras"}]
-- =====================================================================
create or replace function public.wms_cerrar_pallet_recepcion(
  p_bodega text, p_lpn text, p_lineas jsonb,
  p_asn_id bigint default null, p_contenedor text default null, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_lpn text := upper(btrim(coalesce(p_lpn, '')));
  v_usuario text := public.wms_contexto(p_usuario, 'wms_cerrar_pallet_recepcion');
  v_cont text := coalesce(nullif(upper(btrim(p_contenedor)), ''), case when p_asn_id is not null then 'PO-' || p_asn_id end, 'SIN-CONTENEDOR');
  l jsonb;
  v_sku text; v_lote text; v_venc date; v_mult int; v_cajas int; v_sueltas int; v_total int;
  v_n int := 0; v_sum int := 0;
begin
  if v_lpn = '' then raise exception 'WMS: falta el LPN'; end if;
  if jsonb_typeof(p_lineas) is distinct from 'array' or jsonb_array_length(p_lineas) = 0 then
    raise exception 'WMS: el pallet % no tiene líneas', v_lpn;
  end if;
  if p_asn_id is not null and not exists (select 1 from asn_cabecera where id = p_asn_id) then
    raise exception 'WMS: la OC/ASN % no existe', p_asn_id;
  end if;

  perform pg_advisory_xact_lock(hashtext('LPN|' || v_lpn));
  if exists (select 1 from registro_recepcion where lpn = v_lpn)
     or exists (select 1 from bodega_inventario_ubicacion where lpn = v_lpn) then
    raise exception 'WMS: el LPN % ya fue usado. Destruya esa etiqueta y use una nueva.', v_lpn;
  end if;

  for l in select * from jsonb_array_elements(p_lineas) loop
    v_sku := public.wms_normalizar_sku(l->>'sku');
    if v_sku = '' then raise exception 'WMS: hay una línea sin SKU'; end if;
    if not exists (select 1 from maestra_sku where sku = v_sku) then
      raise exception 'WMS: el SKU % no existe en la maestra. Enrólelo antes de recibir.', v_sku;
    end if;
    v_lote := public.wms_normalizar_lote(l->>'lote');
    v_venc := public.wms_fecha_desde_texto(l->>'fecha_vencimiento');
    if coalesce(btrim(l->>'fecha_vencimiento'), '') not in ('', 'S/F') and v_venc is null then
      raise exception 'WMS: vencimiento inválido "%" (SKU %)', l->>'fecha_vencimiento', v_sku;
    end if;
    v_mult    := greatest(coalesce((l->>'multiplo')::int, 1), 1);
    v_cajas   := coalesce((l->>'cajas')::int, 0);
    v_sueltas := coalesce((l->>'unidades_sueltas')::int, 0);
    v_total   := coalesce((l->>'unidades_totales')::int, v_cajas * v_mult + v_sueltas);
    if v_cajas < 0 or v_sueltas < 0 or v_total <= 0 then
      raise exception 'WMS: cantidades inválidas en SKU %', v_sku;
    end if;
    if v_total <> v_cajas * v_mult + v_sueltas then
      raise exception 'WMS: SKU %: % UN no cuadra con % cajas x % + % sueltas', v_sku, v_total, v_cajas, v_mult, v_sueltas;
    end if;

    insert into registro_recepcion (lpn, sku, codigo_barras_escaneado, lote, fecha_vencimiento_cl, multiplo_aplicado,
                                    cajas, unidades_sueltas, unidades_totales, asn_id, contenedor, bodega, operador, fecha_recepcion)
    values (v_lpn, v_sku, coalesce(nullif(l->>'codigo_barras', ''), v_sku), v_lote, public.wms_fecha_cl(v_venc), v_mult,
            v_cajas, v_sueltas, v_total, p_asn_id, v_cont, v_bodega, v_usuario, now());
    perform public.wms_kardex(v_bodega, 'RECEPCION (' || v_cont || ')', v_lpn, v_sku, v_lote, v_cont, 'ANDEN_TRANSITO', v_cajas, v_total);
    v_n := v_n + 1;
    v_sum := v_sum + v_total;
  end loop;

  return jsonb_build_object('lpn', v_lpn, 'lineas', v_n, 'unidades', v_sum, 'bodega', v_bodega);
end $$;

-- =====================================================================
-- 2. CONSULTAR LPN (paso 1 del almacenamiento). Solo lectura.
--    estado: EN_ANDEN | EN_RACK | VARIAS_UBICACIONES | SIN_SALDO | NO_EXISTE
-- =====================================================================
create or replace function public.wms_consultar_lpn(p_bodega text, p_lpn text)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_lpn text := upper(btrim(coalesce(p_lpn, '')));
  v_ubics text[];
  v_otra text;
begin
  if v_lpn ~ '^\d{18}$' then v_lpn := 'SSCC-' || v_lpn; end if;

  select array_agg(distinct codigo_ubicacion) into v_ubics
  from bodega_inventario_ubicacion
  where bodega = v_bodega and lpn = v_lpn and codigo_ubicacion <> 'ZONA-PICKING' and cantidad_unidades > 0;

  if coalesce(array_length(v_ubics, 1), 0) > 1 then
    return jsonb_build_object('estado', 'VARIAS_UBICACIONES', 'lpn', v_lpn, 'ubicaciones', to_jsonb(v_ubics),
      'mensaje', format('El LPN %s figura en %s ubicaciones (%s). Haga conteo cíclico antes de moverlo.', v_lpn, array_length(v_ubics, 1), array_to_string(v_ubics, ', ')));
  elsif coalesce(array_length(v_ubics, 1), 0) = 1 then
    return jsonb_build_object('estado', 'EN_RACK', 'lpn', v_lpn, 'origen', v_ubics[1], 'lineas',
      (select jsonb_agg(jsonb_build_object('id', id, 'sku', sku, 'lote', lote, 'fecha_vencimiento_cl', fecha_vencimiento_cl,
                                           'cajas', cajas, 'unidades_totales', cantidad_unidades) order by id)
       from bodega_inventario_ubicacion
       where bodega = v_bodega and lpn = v_lpn and codigo_ubicacion = v_ubics[1] and cantidad_unidades > 0));
  end if;

  if exists (select 1 from bodega_inventario_ubicacion where bodega = v_bodega and lpn = v_lpn)
     or exists (select 1 from historial_movimientos where bodega = v_bodega and lpn = v_lpn
                and tipo_movimiento in ('ALMACENAMIENTO', 'ENVIO_MERMA')) then
    return jsonb_build_object('estado', 'SIN_SALDO', 'lpn', v_lpn,
      'mensaje', format('El LPN %s ya fue almacenado y no tiene saldo en rack (consumido o movido a picking).', v_lpn));
  end if;

  if exists (select 1 from registro_recepcion where bodega = v_bodega and lpn = v_lpn
             and coalesce(estado_pallet, '') = 'CERRADO_SIN_UBICAR') then
    return jsonb_build_object('estado', 'SIN_SALDO', 'lpn', v_lpn,
      'mensaje', format('La recepción del LPN %s fue cerrada sin ubicar (histórico). Si el pallet está físicamente en bodega, regístrelo con Conteo Cíclico.', v_lpn));
  end if;

  if exists (select 1 from registro_recepcion where bodega = v_bodega and lpn = v_lpn) then
    return jsonb_build_object('estado', 'EN_ANDEN', 'lpn', v_lpn, 'origen', 'ANDEN_TRANSITO', 'lineas',
      (select jsonb_agg(jsonb_build_object('id', id, 'sku', sku, 'lote', lote, 'fecha_vencimiento_cl', fecha_vencimiento_cl,
                                           'cajas', cajas, 'unidades_totales', unidades_totales) order by id)
       from registro_recepcion where bodega = v_bodega and lpn = v_lpn));
  end if;

  select bodega into v_otra from registro_recepcion where lpn = v_lpn limit 1;
  return jsonb_build_object('estado', 'NO_EXISTE', 'lpn', v_lpn, 'mensaje',
    case when v_otra is not null then format('El LPN %s pertenece a %s, no a %s.', v_lpn, v_otra, v_bodega)
         else format('El LPN %s no existe en recepción ni en inventario de %s.', v_lpn, v_bodega) end);
end $$;

-- =====================================================================
-- 3. ALMACENAR / REUBICAR / ENVIAR A MERMA un LPN completo
-- =====================================================================
create or replace function public.wms_almacenar_lpn(
  p_bodega text, p_lpn text, p_ubicacion_destino text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_usuario text := public.wms_contexto(p_usuario, 'wms_almacenar_lpn');
  v_info jsonb;
  v_lpn text;
  v_dest text;
  v_tipo text;
  v_origen text;
  r record;
  v_n int := 0;
  v_unid int := 0;
begin
  v_lpn := upper(btrim(coalesce(p_lpn, '')));
  if v_lpn ~ '^\d{18}$' then v_lpn := 'SSCC-' || v_lpn; end if;
  perform pg_advisory_xact_lock(hashtext('LPN|' || v_lpn));

  v_dest := public.wms_ubicacion_valida(v_bodega, p_ubicacion_destino);
  v_tipo := case when v_dest = 'ZONA-MERMA' then 'ENVIO_MERMA' else 'ALMACENAMIENTO' end;
  v_info := public.wms_consultar_lpn(v_bodega, v_lpn);

  if v_info->>'estado' = 'EN_RACK' then
    v_origen := v_info->>'origen';
    if v_origen = v_dest then
      raise exception 'WMS: el LPN % ya está en %', v_lpn, v_dest;
    end if;
    for r in select * from bodega_inventario_ubicacion
              where bodega = v_bodega and lpn = v_lpn and codigo_ubicacion = v_origen
              order by id for update loop
      delete from bodega_inventario_ubicacion where id = r.id;
      perform public.wms_sumar_en_ubicacion(v_bodega, v_dest, r.sku, r.lote, r.lpn, r.fecha_vencimiento_cl, r.cajas, r.cantidad_unidades);
      perform public.wms_kardex(v_bodega, v_tipo, v_lpn, r.sku, r.lote, v_origen, v_dest, r.cajas, r.cantidad_unidades);
      v_n := v_n + 1; v_unid := v_unid + r.cantidad_unidades;
    end loop;

  elsif v_info->>'estado' = 'EN_ANDEN' then
    v_origen := 'ANDEN_TRANSITO';
    for r in select * from registro_recepcion where bodega = v_bodega and lpn = v_lpn order by id for update loop
      perform public.wms_sumar_en_ubicacion(v_bodega, v_dest, r.sku, r.lote, v_lpn, r.fecha_vencimiento_cl, r.cajas, r.unidades_totales);
      perform public.wms_kardex(v_bodega, v_tipo, v_lpn, r.sku, r.lote, v_origen, v_dest, r.cajas, r.unidades_totales);
      v_n := v_n + 1; v_unid := v_unid + r.unidades_totales;
    end loop;
    update registro_recepcion set ubicacion_destino = v_dest, estado_pallet = 'ALMACENADO'
     where bodega = v_bodega and lpn = v_lpn;

  else
    raise exception 'WMS: %', coalesce(v_info->>'mensaje', 'el LPN no se puede almacenar');
  end if;

  return jsonb_build_object('lpn', v_lpn, 'origen', v_origen, 'destino', v_dest, 'lineas', v_n, 'unidades', v_unid, 'tipo', v_tipo);
end $$;

-- =====================================================================
-- 4. MOVER A PICKING (reabastecimiento) desde una fila de inventario
-- =====================================================================
create or replace function public.wms_mover_a_picking(
  p_inventario_id bigint, p_cajas integer, p_destino text default 'ZONA-PICKING', p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_usuario text := public.wms_contexto(p_usuario, 'wms_mover_a_picking');
  o record;
  v_dest text;
  v_mult int;
  v_cajas int;
  v_unid int;
begin
  select * into o from bodega_inventario_ubicacion where id = p_inventario_id for update;
  if not found then
    raise exception 'WMS: el stock seleccionado ya no existe (otro operador lo movió). Vuelva a buscar el SKU.';
  end if;
  if o.lote like '%|QA:%' then
    raise exception 'WMS: el lote % está bloqueado por calidad y no puede ir a picking', o.lote;
  end if;
  v_dest := public.wms_ubicacion_valida(o.bodega, coalesce(nullif(btrim(p_destino), ''), 'ZONA-PICKING'));
  if v_dest = o.codigo_ubicacion then
    raise exception 'WMS: el destino debe ser distinto del origen (%)', o.codigo_ubicacion;
  end if;
  if coalesce(p_cajas, 0) <= 0 then
    raise exception 'WMS: indique cuántas cajas mover';
  end if;

  v_mult := case when coalesce(o.cajas, 0) > 0 then greatest(round(o.cantidad_unidades::numeric / o.cajas)::int, 1) else 1 end;
  if coalesce(o.cajas, 0) > 0 and p_cajas > o.cajas then
    raise exception 'WMS: solo hay % cajas en %', o.cajas, o.codigo_ubicacion;
  end if;
  v_cajas := least(p_cajas, greatest(coalesce(o.cajas, 0), p_cajas));
  v_unid  := case when coalesce(o.cajas, 0) > 0 and v_cajas >= o.cajas then o.cantidad_unidades
                  else least(v_cajas * v_mult, o.cantidad_unidades) end;

  if o.cantidad_unidades - v_unid <= 0 then
    delete from bodega_inventario_ubicacion where id = o.id;
  else
    update bodega_inventario_ubicacion
       set cantidad_unidades = cantidad_unidades - v_unid,
           cajas = greatest(coalesce(cajas, 0) - v_cajas, 0),
           auditor = v_usuario, fecha = now()::text
     where id = o.id;
  end if;
  perform public.wms_sumar_en_ubicacion(o.bodega, v_dest, o.sku, o.lote, o.lpn, o.fecha_vencimiento_cl, v_cajas, v_unid);
  perform public.wms_kardex(o.bodega, 'MOVIMIENTO_PICKING', o.lpn, o.sku, o.lote, o.codigo_ubicacion, v_dest, v_cajas, v_unid);

  return jsonb_build_object('origen', o.codigo_ubicacion, 'destino', v_dest, 'cajas', v_cajas, 'unidades', v_unid, 'sku', o.sku, 'lote', o.lote);
end $$;

-- =====================================================================
-- 5. SALIDA POR PICKING: descuenta del stock lo pickeado para una OV.
--    Prioridad: ubicación informada -> ZONA-PICKING -> FEFO (vence antes).
--    Si no hay stock registrado, NO inventa saldo negativo: devuelve el
--    faltante y lo deja en el kardex como SALIDA_PICKING_SIN_STOCK.
-- =====================================================================
create or replace function public.wms_salida_picking(
  p_bodega text, p_sku text, p_lote text, p_unidades integer, p_numero_ov text,
  p_usuario text default null, p_ubicacion text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_usuario text := public.wms_contexto(p_usuario, 'wms_salida_picking');
  v_sku text := public.wms_normalizar_sku(p_sku);
  v_lote text := split_part(public.wms_normalizar_lote(p_lote), '|QA:', 1);
  v_ubic text := public.wms_normalizar_ubicacion(p_ubicacion);
  v_ov text := upper(btrim(coalesce(p_numero_ov, 'S/OV')));
  v_pend int := coalesce(p_unidades, 0);
  v_tomar int;
  v_cajas_nuevas int;
  v_mult int;
  v_detalle jsonb := '[]'::jsonb;
  r record;
begin
  if v_sku like '%-FA' then v_sku := left(v_sku, length(v_sku) - 3); end if;
  if v_pend <= 0 then
    raise exception 'WMS: la cantidad a descontar debe ser mayor a 0';
  end if;

  for r in
    select * from bodega_inventario_ubicacion
     where bodega = v_bodega and sku in (v_sku, v_sku || '-FA') and lote = v_lote
       and codigo_ubicacion <> 'ZONA-MERMA' and cantidad_unidades > 0
     order by case when v_ubic <> '' and codigo_ubicacion = v_ubic then 0
                   when codigo_ubicacion = 'ZONA-PICKING' then 1 else 2 end,
              fecha_vencimiento nulls last, id
     for update
  loop
    exit when v_pend <= 0;
    v_tomar := least(v_pend, r.cantidad_unidades);
    if r.cantidad_unidades - v_tomar <= 0 then
      delete from bodega_inventario_ubicacion where id = r.id;
      v_cajas_nuevas := 0;
    else
      v_mult := case when coalesce(r.cajas, 0) > 0 then greatest(round(r.cantidad_unidades::numeric / r.cajas)::int, 1) else 1 end;
      v_cajas_nuevas := case when coalesce(r.cajas, 0) > 0 then (r.cantidad_unidades - v_tomar) / v_mult else 0 end;
      update bodega_inventario_ubicacion
         set cantidad_unidades = cantidad_unidades - v_tomar, cajas = v_cajas_nuevas,
             auditor = v_usuario, fecha = now()::text
       where id = r.id;
    end if;
    perform public.wms_kardex(v_bodega, 'SALIDA_PICKING (' || v_ov || ')', r.lpn, r.sku, r.lote, r.codigo_ubicacion,
                              'PACKING ' || v_ov, coalesce(r.cajas, 0) - v_cajas_nuevas, v_tomar);
    v_detalle := v_detalle || jsonb_build_object('ubicacion', r.codigo_ubicacion, 'lpn', r.lpn, 'unidades', v_tomar);
    v_pend := v_pend - v_tomar;
  end loop;

  if v_pend > 0 then
    perform public.wms_kardex(v_bodega, 'SALIDA_PICKING_SIN_STOCK (' || v_ov || ')', null, v_sku, v_lote, 'SIN_REGISTRO',
                              'PACKING ' || v_ov, 0, v_pend);
  end if;

  return jsonb_build_object('sku', v_sku, 'lote', v_lote, 'solicitado', p_unidades,
                            'descontado', p_unidades - v_pend, 'faltante', v_pend, 'detalle', v_detalle);
end $$;

-- =====================================================================
-- 6. CONTEO CÍCLICO / AJUSTE
--    p_modo = 'SUMAR' (conteo por pasadas) | 'FIJAR' (cantidad contada final)
--    p_inventario_id: corregir una fila puntual (modo edición del celular)
-- =====================================================================
create or replace function public.wms_registrar_conteo(
  p_bodega text, p_ubicacion text, p_sku text, p_lote text, p_vencimiento text,
  p_lpn text, p_cajas integer, p_modo text default 'SUMAR',
  p_inventario_id bigint default null, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_usuario text := public.wms_contexto(p_usuario, 'wms_registrar_conteo');
  v_ubic text;
  v_sku text := public.wms_normalizar_sku(p_sku);
  v_lote text := public.wms_normalizar_lote(p_lote);
  v_lpn text := nullif(upper(btrim(coalesce(p_lpn, ''))), '');
  v_venc date := public.wms_fecha_desde_texto(p_vencimiento);
  v_mult int;
  v_unid int;
  v_modo text := upper(coalesce(p_modo, 'SUMAR'));
  o record;
  v_cajas_ant int := 0;
  v_unid_ant int := 0;
  v_cajas_fin int;
  v_unid_fin int;
  v_tipo text;
begin
  if v_sku = '' then raise exception 'WMS: falta el SKU'; end if;
  if coalesce(p_cajas, -1) < 0 then raise exception 'WMS: la cantidad contada no es válida'; end if;
  if coalesce(btrim(p_vencimiento), '') not in ('', 'S/F') and v_venc is null then
    raise exception 'WMS: vencimiento inválido "%". Use DD-MM-YYYY', p_vencimiento;
  end if;
  if v_modo not in ('SUMAR', 'FIJAR') then raise exception 'WMS: modo de conteo inválido %', p_modo; end if;
  v_ubic := public.wms_ubicacion_valida(v_bodega, p_ubicacion);
  select greatest(coalesce(max(multiplo), 1), 1) into v_mult from maestra_sku where sku = v_sku;
  v_unid := p_cajas * v_mult;

  if p_inventario_id is not null then
    select * into o from bodega_inventario_ubicacion where id = p_inventario_id for update;
    if not found then raise exception 'WMS: la línea de inventario % ya no existe', p_inventario_id; end if;
    v_modo := 'FIJAR';
  else
    perform pg_advisory_xact_lock(hashtext('INV|' || v_bodega || '|' || v_ubic || '|' || v_sku || '|' || v_lote || '|' || coalesce(v_lpn, '')));
    select * into o from bodega_inventario_ubicacion
     where bodega = v_bodega and codigo_ubicacion = v_ubic and sku = v_sku and lote = v_lote and lpn is not distinct from v_lpn
     order by id limit 1 for update;
  end if;

  if found then
    v_cajas_ant := coalesce(o.cajas, 0);
    v_unid_ant := o.cantidad_unidades;
  end if;
  v_cajas_fin := case when v_modo = 'SUMAR' then v_cajas_ant + p_cajas else p_cajas end;
  v_unid_fin  := case when v_modo = 'SUMAR' then v_unid_ant + v_unid else v_unid end;

  if o.id is not null then
    if v_unid_fin <= 0 then
      delete from bodega_inventario_ubicacion where id = o.id;
    else
      update bodega_inventario_ubicacion
         set codigo_ubicacion = v_ubic, lote = v_lote, lpn = v_lpn, sku = v_sku,
             fecha_vencimiento_cl = coalesce(public.wms_fecha_cl(v_venc), fecha_vencimiento_cl),
             cajas = v_cajas_fin, cantidad_unidades = v_unid_fin, auditor = v_usuario, fecha = now()::text
       where id = o.id;
    end if;
  elsif v_unid_fin > 0 then
    perform public.wms_sumar_en_ubicacion(v_bodega, v_ubic, v_sku, v_lote, v_lpn, public.wms_fecha_cl(v_venc), v_cajas_fin, v_unid_fin);
  else
    return jsonb_build_object('sin_cambios', true, 'mensaje', 'Cantidad 0 en una ubicación sin stock: no se registró nada.');
  end if;

  v_tipo := case when p_inventario_id is not null then 'AJUSTE_CICLICO_MODIFICACION'
                 when v_unid_fin - v_unid_ant >= 0 then 'AJUSTE_CICLICO_SUMA' else 'AJUSTE_CICLICO_RESTA' end;
  if v_unid_fin <> v_unid_ant or v_cajas_fin <> v_cajas_ant then
    perform public.wms_kardex(v_bodega, v_tipo, v_lpn, v_sku, v_lote, coalesce(o.codigo_ubicacion, v_ubic), v_ubic,
                              v_cajas_fin - v_cajas_ant, v_unid_fin - v_unid_ant);
  end if;

  return jsonb_build_object('ubicacion', v_ubic, 'sku', v_sku, 'lote', v_lote, 'multiplo', v_mult,
                            'cajas_antes', v_cajas_ant, 'cajas_despues', v_cajas_fin,
                            'unidades_antes', v_unid_ant, 'unidades_despues', v_unid_fin);
end $$;

-- =====================================================================
-- 7. LOGIN sin exponer contraseñas (acepta texto plano antiguo y bcrypt)
-- =====================================================================
create or replace function public.wms_login(p_usuario text, p_password text)
returns jsonb language plpgsql security definer set search_path = public, extensions as $$
declare
  u record;
  v_ok boolean := false;
begin
  select * into u from wms_usuarios where upper(btrim(usuario)) = upper(btrim(coalesce(p_usuario, ''))) limit 1;
  if found and coalesce(p_password, '') <> '' then
    if u.password ~ '^\$2[aby]\$' then
      v_ok := extensions.crypt(p_password, u.password) = u.password;
    else
      v_ok := u.password = p_password;
    end if;
  end if;
  if not v_ok then
    perform pg_sleep(1);  -- frena ataques de fuerza bruta
    return null;
  end if;
  if not coalesce(u.activo, false) then
    return jsonb_build_object('error', 'USUARIO_INACTIVO');
  end if;
  return jsonb_build_object('id', u.id, 'usuario', u.usuario, 'nombre_completo', u.nombre_completo, 'rol', u.rol,
                            'bodega', u.bodega, 'activo', u.activo, 'modulos_pc', to_jsonb(u.modulos_pc),
                            'modulos_rf', to_jsonb(u.modulos_rf), 'pasillo_asignado', u.pasillo_asignado);
end $$;

-- Cambio de contraseña: se guarda cifrada (bcrypt). Solo el PC (clave secreta).
create or replace function public.wms_cambiar_password(p_usuario_id bigint, p_password text)
returns void language plpgsql security definer set search_path = public, extensions as $$
begin
  if length(coalesce(p_password, '')) < 4 then
    raise exception 'WMS: la contraseña debe tener al menos 4 caracteres';
  end if;
  update wms_usuarios set password = extensions.crypt(p_password, extensions.gen_salt('bf')), updated_at = now()
   where id = p_usuario_id;
  if not found then raise exception 'WMS: usuario % no existe', p_usuario_id; end if;
end $$;

-- ---------------------------------------------------------------------
-- Permisos de ejecución
-- ---------------------------------------------------------------------
revoke all on function public.wms_contexto(text, text) from public, anon, authenticated;
revoke all on function public.wms_kardex(text, text, text, text, text, text, text, integer, integer) from public, anon, authenticated;
revoke all on function public.wms_sumar_en_ubicacion(text, text, text, text, text, text, integer, integer) from public, anon, authenticated;
revoke all on function public.wms_ubicacion_valida(text, text) from public, anon, authenticated;
revoke all on function public.wms_cambiar_password(bigint, text) from public, anon, authenticated;
grant execute on function public.wms_cambiar_password(bigint, text) to service_role;

grant execute on function public.wms_cerrar_pallet_recepcion(text, text, jsonb, bigint, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_consultar_lpn(text, text) to anon, authenticated, service_role;
grant execute on function public.wms_almacenar_lpn(text, text, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_mover_a_picking(bigint, integer, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_salida_picking(text, text, text, integer, text, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_registrar_conteo(text, text, text, text, text, text, integer, text, bigint, text) to anon, authenticated, service_role;
grant execute on function public.wms_login(text, text) to anon, authenticated, service_role;

commit;
