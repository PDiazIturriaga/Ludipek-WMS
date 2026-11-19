-- =====================================================================
-- LUDIPEK WMS · 12 DESPACHO COMO DATO PROPIO + VERSIÓN MÍNIMA DE LA APP  (requiere 10 y 11)
-- 1) wms_despacho_ov: bultos, tipo de empaque, comuna, peso, LPN, faltante y mesa
--    de cada orden empacada, en columnas (antes iban como texto dentro de
--    canal_venta y en un archivo JSON local de cada PC).
-- 2) Al cerrar el packing la OV entra sola a wms_despacho_rutas (Ruteo) con sus
--    bultos y kilos reales; si ya estaba, se actualizan sin tocar camión/chofer.
-- 3) wms_config + wms_version_minima(): la app del celular no deja entrar a una
--    versión antigua (para que no se repita lo de la OV 133409-FA).
-- =====================================================================
begin;

-- ---------- 1. Configuración y versión mínima ----------
create table if not exists public.wms_config (
  clave text primary key,
  valor text not null,
  descripcion text,
  actualizado_en timestamptz not null default now()
);
alter table public.wms_config enable row level security;
insert into public.wms_config (clave, valor, descripcion) values
  ('version_minima_rf', '2026.11.19', 'Versión mínima de la app del celular (AAAA.MM.DD). Subirla obliga a recargar la app.')
on conflict (clave) do nothing;

create or replace function public.wms_version_minima()
returns text language sql stable security definer set search_path = public as $$
  select coalesce((select valor from wms_config where clave = 'version_minima_rf'), '0');
$$;
grant execute on function public.wms_version_minima() to anon, authenticated, service_role;

-- ---------- 2. Despacho por orden ----------
create table if not exists public.wms_despacho_ov (
  orden_id bigint primary key references public.netsuite_ordenes_venta(id) on delete cascade,
  numero_ov text not null,
  bodega text not null default 'Bodega Santiago',
  cliente_nombre text,
  modo text not null default 'BULTOS',
  bultos integer not null check (bultos >= 1),
  tipo_empaque text,
  comuna text,
  lpn text,
  peso_esperado_kg numeric,
  peso_real_kg numeric,
  unidades integer not null default 0,
  faltante_un integer not null default 0 check (faltante_un >= 0),
  motivo_faltante text,
  mesa_packing text,
  packing_list_id bigint,
  cerrado_por text,
  cerrado_en timestamptz not null default now()
);
create index if not exists idx_despacho_ov_bodega on public.wms_despacho_ov (bodega, cerrado_en desc);
alter table public.wms_despacho_ov enable row level security;

-- Respaldo: órdenes ya empacadas con datos en canal_venta (BULTOS:3|TIPO:CAJA|...)
insert into public.wms_despacho_ov (orden_id, numero_ov, bodega, cliente_nombre, bultos, tipo_empaque, comuna, lpn,
                                    peso_real_kg, unidades, faltante_un, motivo_faltante, mesa_packing, cerrado_en)
select o.id, o.numero_ov, coalesce(o.bodega, 'Bodega Santiago'), o.cliente_nombre,
       greatest(coalesce(nullif(substring(o.canal_venta from 'BULTOS:(\d+)'), '')::int, 1), 1),
       substring(o.canal_venta from 'TIPO:([^|]+)'),
       substring(o.canal_venta from 'COMUNA:([^|]+)'),
       substring(o.canal_venta from 'LPN:([^|]+)'),
       nullif(substring(o.canal_venta from 'PESO_KG:([0-9.]+)'), '')::numeric,
       (select coalesce(sum(d.cantidad_pickeada), 0) from netsuite_detalle_ov d where d.orden_id = o.id),
       coalesce(nullif(substring(o.canal_venta from 'FALTANTE:(\d+)'), '')::int, 0),
       substring(o.canal_venta from 'MOTIVO_FALTANTE:([^|]+)'),
       o.mesa_packing, coalesce(o.updated_at, now())
from public.netsuite_ordenes_venta o
where o.canal_venta ~ 'BULTOS:\d+'
on conflict (orden_id) do nothing;

-- Lectura para el celular y el PC (solo lectura; se escribe únicamente vía wms_cerrar_packing)
create or replace function public.wms_despacho_de_orden(p_orden_id bigint)
returns setof public.wms_despacho_ov language sql stable security definer set search_path = public as $$
  select * from wms_despacho_ov where orden_id = p_orden_id;
$$;
grant execute on function public.wms_despacho_de_orden(bigint) to anon, authenticated, service_role;

-- ---------- 3. Cierre de packing (misma firma que el script 10) ----------
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
  v_peso numeric := coalesce(p_peso_real_kg, p_peso_esperado_kg);
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

  -- 5) Datos de despacho en su propia tabla (una fila por orden) y entrada directa a ruteo
  insert into wms_despacho_ov (orden_id, numero_ov, bodega, cliente_nombre, modo, bultos, tipo_empaque, comuna,
                               lpn, peso_esperado_kg, peso_real_kg, unidades, faltante_un, motivo_faltante,
                               mesa_packing, packing_list_id, cerrado_por, cerrado_en)
  values (p_orden_id, o.numero_ov, coalesce(o.bodega, 'Bodega Santiago'), o.cliente_nombre, v_modo, p_bultos,
          nullif(upper(btrim(p_tipo_empaque)), ''), nullif(upper(btrim(p_comuna)), ''), v_lpn,
          p_peso_esperado_kg, p_peso_real_kg, v_total, v_faltante, case when v_faltante > 0 then v_motivo end,
          o.mesa_packing, v_pl_id, v_usuario, now())
  on conflict (orden_id) do update set
    bultos = excluded.bultos, tipo_empaque = excluded.tipo_empaque, comuna = excluded.comuna, lpn = excluded.lpn,
    peso_esperado_kg = excluded.peso_esperado_kg, peso_real_kg = excluded.peso_real_kg, unidades = excluded.unidades,
    faltante_un = excluded.faltante_un, motivo_faltante = excluded.motivo_faltante, mesa_packing = excluded.mesa_packing,
    packing_list_id = excluded.packing_list_id, cerrado_por = excluded.cerrado_por, cerrado_en = excluded.cerrado_en,
    modo = excluded.modo;

  if upper(o.numero_ov) not like 'OT-%' then
    insert into wms_despacho_rutas (bodega, numero_ov, cliente, comuna, peso_kg, tipo_empaque, cantidad_bultos,
                                    etiqueta_bultos, fecha_picking, estado_validado_ns, status_entrega, usuario_modificacion)
    values (coalesce(o.bodega, 'Bodega Santiago'), regexp_replace(upper(o.numero_ov), '-FA$', ''), coalesce(o.cliente_nombre, ''),
            coalesce(nullif(upper(btrim(p_comuna)), ''), 'SANTIAGO'), coalesce(v_peso, 0),
            coalesce(nullif(upper(btrim(p_tipo_empaque)), ''), 'BULTOS'), p_bultos,
            case when upper(coalesce(p_tipo_empaque, '')) = 'PALLET' then 'P ' else 'B ' end || p_bultos,
            to_char(now(), 'YYYY-MM-DD'), 'PENDIENTE_FACTURACION', 'PENDIENTE RUTA', v_usuario)
    on conflict (numero_ov) do update set
      cantidad_bultos = excluded.cantidad_bultos, tipo_empaque = excluded.tipo_empaque,
      etiqueta_bultos = excluded.etiqueta_bultos,
      peso_kg = case when excluded.peso_kg > 0 then excluded.peso_kg else wms_despacho_rutas.peso_kg end,
      comuna = case when excluded.comuna <> '' then excluded.comuna else wms_despacho_rutas.comuna end,
      fecha_picking = excluded.fecha_picking, estado_validado_ns = excluded.estado_validado_ns,
      usuario_modificacion = excluded.usuario_modificacion, updated_at = now();
  end if;

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

-- Para obligar a todos los celulares a recargar la app después de un cambio:
-- update public.wms_config set valor = '2026.11.20', actualizado_en = now() where clave = 'version_minima_rf';
