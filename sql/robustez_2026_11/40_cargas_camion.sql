-- =====================================================================
-- LUDIPEK WMS · 40 CARGA DE CAMIÓN Y OT "LISTA PARA CARGA"   (requiere 12, 13, 31, 38 y 39)
--
-- A) La OT ya NO pasa a "en tránsito" al terminar el picking: queda LISTA_PARA_CARGA en
--    Santiago. Recién al cerrar la carga del camión pasa a EN_TRANSITO_CCP y Concepción la ve.
-- B) Carga de camión (celular y PC): patente / contenedor, se le anclan OT u OV y se escanea
--    cada pallet o bulto al subirlo (pallet 1/10, 2/10...). OV: solo control (no cambia su estado).
-- C) Ajustes antes de cargar (PC): cambiar lote/fecha de cajas (con su stock), mover cajas entre
--    pallets, quitar un pallet de la carga (viaja en otro camión) y reabrir la OT a picking.
-- D) Concepción: ve qué pallets siguen en Santiago y no puede darlos por "no llegó".
--    Las fotos de las cajas quedan solo para Santiago (el PC de Concepción ya no las muestra).
-- E) Permisos: Picking OT y Carga de camión son módulos propios (APP_PICKING_OT, APP_CARGA_CAMION,
--    PC_CARGAS). Quien tenía Picking farmacia recibe Picking OT; quien tenía Packing recibe Carga.
-- =====================================================================
begin;

-- =====================================================================
-- A) Estado LISTA_PARA_CARGA
-- =====================================================================
create or replace function public.wms_orden_estado_ov(p text)
returns integer language sql immutable as $$
  select case upper(coalesce(p, ''))
    when '' then 0 when 'PENDIENTE' then 5 when 'PENDIENTE_PICKING' then 10
    when 'PICKING_EN_PROCESO' then 20 when 'PICKING_COMPLETO' then 30
    when 'PENDIENTE_PACKING' then 40 when 'PACKING_EN_PROCESO' then 50
    when 'PENDIENTE_FACTURACION' then 70 when 'LISTA_PARA_CARGA' then 70 when 'EN_TRANSITO_CCP' then 70
    when 'RECEPCION_CCP_EN_PROCESO' then 80 when 'FACTURADO' then 80
    when 'RECIBIDO_CCP' then 90 when 'RECIBIDO_CCP_CON_DIFERENCIAS' then 90
    when 'DESPACHADO' then 90 when 'ANULADO' then 99 when 'CERRADO' then 99
    else 50 end;
$$;

insert into public.wms_catalogo_estados (codigo, modulo, descripcion, orden_flujo, color_hex)
values ('LISTA_PARA_CARGA', 'SALIDA', 'OT pickeada en pallets, esperando la carga del camión', 65, '#A78BFA')
on conflict (codigo) do update set descripcion = excluded.descripcion;

-- Cierre del packing (también lo usa el cierre del picking de OT): la OT queda LISTA_PARA_CARGA
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
  v_tok text;
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
  -- canal_venta es varchar(100) en producción: el detalle completo vive en wms_despacho_ov y aquí
  -- solo van las marcas que caben, por prioridad (canal original, faltante, bultos, LPN, ...).
  v_canal := left(coalesce(nullif(v_canal, ''), ''), 60);
  foreach v_tok in array array[
      case when v_faltante > 0 then 'FALTANTE:' || v_faltante end,
      'BULTOS:' || p_bultos,
      case when v_lpn is not null then 'LPN:' || v_lpn end,
      case when p_peso_real_kg is not null then 'PESO_KG:' || round(p_peso_real_kg, 2)
           when p_peso_esperado_kg is not null then 'PESO_KG:' || round(p_peso_esperado_kg, 2) end,
      case when nullif(btrim(p_tipo_empaque), '') is not null then 'TIPO:' || upper(btrim(p_tipo_empaque)) end,
      case when nullif(btrim(p_comuna), '') is not null then 'COMUNA:' || upper(btrim(p_comuna)) end,
      case when v_faltante > 0 then 'MOTIVO_FALTANTE:' || replace(upper(v_motivo), '|', '/') end]
  loop
    continue when v_tok is null;
    if length(concat_ws('|', nullif(v_canal, ''), v_tok)) <= 100 then
      v_canal := concat_ws('|', nullif(v_canal, ''), v_tok);
    end if;
  end loop;
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

  v_destino := case when upper(o.numero_ov) like 'OT-%' then 'LISTA_PARA_CARGA' else 'PENDIENTE_FACTURACION' end;
  v_estado := public.wms_cambiar_estado_ov(p_orden_id, v_destino, v_usuario,
      format('Packing %s: %s bultos, %s UN%s%s', v_modo, p_bultos, v_total,
             case when p_peso_real_kg is not null then ', ' || round(p_peso_real_kg, 2) || ' kg reales' else '' end,
             case when v_faltante > 0 then format(' · CON FALTANTE %s UN (%s): %s', v_faltante, v_motivo, rtrim(v_detalle_falt, '; ')) else '' end),
      true);
  return v_estado || jsonb_build_object('packing_list_id', v_pl_id, 'unidades', v_total, 'bultos', p_bultos, 'faltante', v_faltante);
end $$;

-- =====================================================================
-- B) Tablas de carga
-- =====================================================================
create table if not exists public.wms_cargas (
  id          bigint generated by default as identity primary key,
  numero      text unique,
  bodega      text not null default 'Bodega Santiago',
  patente     text not null,
  contenedor  text,
  chofer      text,
  destino     text,
  estado      text not null default 'ABIERTA' check (estado in ('ABIERTA', 'CERRADA', 'ANULADA')),
  observacion text,
  creado_por  text,
  creado_en   timestamptz not null default now(),
  cerrado_por text,
  cerrado_en  timestamptz
);
create index if not exists idx_cargas_bodega_estado on public.wms_cargas (bodega, estado, creado_en desc);

create table if not exists public.wms_carga_ordenes (
  id           bigint generated by default as identity primary key,
  carga_id     bigint not null references public.wms_cargas(id) on delete cascade,
  orden_id     bigint not null references public.netsuite_ordenes_venta(id) on delete cascade,
  numero_ov    text not null,
  tipo         text not null check (tipo in ('OT', 'OV')),
  agregado_por text,
  agregado_en  timestamptz not null default now(),
  unique (carga_id, orden_id)
);

create table if not exists public.wms_carga_items (
  id          bigint generated by default as identity primary key,
  carga_id    bigint not null references public.wms_cargas(id) on delete cascade,
  orden_id    bigint not null references public.netsuite_ordenes_venta(id) on delete cascade,
  numero_ov   text not null,
  tipo        text not null check (tipo in ('PALLET', 'BULTO')),
  codigo      text not null,          -- LPN del pallet o código del bulto (etiqueta de packing)
  n           integer not null default 1,
  total       integer not null default 1,
  cajas       integer,
  unidades    integer,
  estado      text not null default 'PENDIENTE' check (estado in ('PENDIENTE', 'CARGADO', 'QUITADO')),
  cargado_por text,
  cargado_en  timestamptz,
  motivo      text,
  unique (carga_id, codigo)
);
create index if not exists idx_carga_items_orden on public.wms_carga_items (orden_id, estado);
create index if not exists idx_carga_items_codigo on public.wms_carga_items (codigo);

-- Registro de los ajustes hechos a una OT antes de cargarla
create table if not exists public.wms_ot_ajustes (
  id        bigint generated by default as identity primary key,
  orden_id  bigint not null references public.netsuite_ordenes_venta(id) on delete cascade,
  numero_ov text not null,
  tipo      text not null,            -- CAMBIO_LOTE / MOVER_CAJAS / REABRIR_PICKING
  detalle   jsonb not null default '{}'::jsonb,
  motivo    text,
  usuario   text,
  creado_en timestamptz not null default now()
);
create index if not exists idx_ot_ajustes_orden on public.wms_ot_ajustes (orden_id, creado_en desc);

alter table public.wms_cargas enable row level security;
alter table public.wms_carga_ordenes enable row level security;
alter table public.wms_carga_items enable row level security;
alter table public.wms_ot_ajustes enable row level security;
revoke all on public.wms_cargas, public.wms_carga_ordenes, public.wms_carga_items, public.wms_ot_ajustes from anon, authenticated;
grant select, insert, update, delete on public.wms_cargas, public.wms_carga_ordenes, public.wms_carga_items, public.wms_ot_ajustes to service_role;
grant usage, select on all sequences in schema public to service_role;
do $$ begin
  if to_regprocedure('public.wms_pc_autorizado()') is not null then   -- script 36: sesiones de PC
    execute 'drop policy if exists wms_pc_sesion on public.wms_cargas';
    execute 'create policy wms_pc_sesion on public.wms_cargas for select to authenticated using ((select public.wms_pc_autorizado()))';
    execute 'drop policy if exists wms_pc_sesion on public.wms_carga_ordenes';
    execute 'create policy wms_pc_sesion on public.wms_carga_ordenes for select to authenticated using ((select public.wms_pc_autorizado()))';
    execute 'drop policy if exists wms_pc_sesion on public.wms_carga_items';
    execute 'create policy wms_pc_sesion on public.wms_carga_items for select to authenticated using ((select public.wms_pc_autorizado()))';
    execute 'drop policy if exists wms_pc_sesion on public.wms_ot_ajustes';
    execute 'create policy wms_pc_sesion on public.wms_ot_ajustes for select to authenticated using ((select public.wms_pc_autorizado()))';
    execute 'grant select on public.wms_cargas, public.wms_carga_ordenes, public.wms_carga_items, public.wms_ot_ajustes to authenticated';
  end if;
end $$;

-- =====================================================================
-- Funciones de apoyo
-- =====================================================================
create or replace function public.wms_usuario_carga(p_usuario text)
returns text language plpgsql security definer set search_path = public as $$
begin
  return public.wms_contexto(p_usuario, 'carga_camion');
exception when others then
  if sqlerrm like '%SESION_EXPIRADA%' then raise; end if;
  return coalesce(nullif(upper(btrim(coalesce(p_usuario, ''))), ''), 'APP');
end $$;

-- Código leído de una etiqueta: "LPN-100912", "LPN-100912|OT-CCP-0102|PALLET:1/2", SSCC de 18 dígitos
create or replace function public.wms_codigo_carga(p_codigo text)
returns text language sql immutable as $$
  select case when x ~ '^\d{18}$' then 'SSCC-' || x else x end
  from (select upper(btrim(split_part(coalesce(p_codigo, ''), '|', 1))) x) z;
$$;

-- ¿El pallet de la OT sigue en Santiago? (la OT ya salió en otra carga y este pallet no iba en ella)
create or replace function public.wms_ot_lpn_en_santiago(p_orden_id bigint, p_lpn text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from wms_carga_items i join wms_cargas c on c.id = i.carga_id
                  where i.orden_id = p_orden_id and c.estado = 'CERRADA' and i.estado = 'CARGADO')
     and not exists (select 1 from wms_carga_items i join wms_cargas c on c.id = i.carga_id
                      where i.orden_id = p_orden_id and upper(i.codigo) = upper(p_lpn)
                        and c.estado = 'CERRADA' and i.estado = 'CARGADO');
$$;

-- Pallets de la OT que todavía no salen de Santiago
create or replace function public.wms_ot_pallets_por_cargar(p_orden_id bigint)
returns table(lpn text, cajas integer, unidades integer, skus integer)
language sql stable security definer set search_path = public as $$
  select x.lpn, sum(x.cajas)::int, sum(x.unidades)::int, count(distinct x.sku)::int
  from public.wms_traslado_lineas_despachadas(p_orden_id) x
  where not exists (select 1 from wms_carga_items i join wms_cargas c on c.id = i.carga_id
                     where i.orden_id = p_orden_id and upper(i.codigo) = x.lpn
                       and c.estado = 'CERRADA' and i.estado = 'CARGADO')
  group by x.lpn
  order by x.lpn;
$$;

-- ¿Ya salió algún pallet de esta OT en una carga cerrada?
create or replace function public.wms_ot_salio_en_carga(p_orden_id bigint)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from wms_carga_items i join wms_cargas c on c.id = i.carga_id
                  where i.orden_id = p_orden_id and c.estado = 'CERRADA' and i.estado = 'CARGADO');
$$;

-- Vuelve a numerar los pallets/bultos de una orden dentro de una carga (1/3, 2/3, 3/3)
create or replace function public.wms_carga_renumerar(p_carga_id bigint, p_orden_id bigint)
returns void language sql security definer set search_path = public as $$
  update wms_carga_items i set n = z.n, total = z.total
  from (select id, row_number() over (order by codigo)::int n, count(*) over ()::int total
          from wms_carga_items where carga_id = p_carga_id and orden_id = p_orden_id) z
  where i.id = z.id;
$$;

-- Resumen de una carga (lo que muestran el celular y el PC)
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
    'ordenes', coalesce((
      select jsonb_agg(jsonb_build_object(
               'orden_id', o.orden_id, 'numero_ov', o.numero_ov, 'tipo', o.tipo,
               'cliente', v.cliente_nombre, 'estado_orden', upper(coalesce(v.estado_ns, v.estado)),
               'total', (select count(*) from wms_carga_items i where i.carga_id = c.id and i.orden_id = o.orden_id and i.estado <> 'QUITADO'),
               'cargados', (select count(*) from wms_carga_items i where i.carga_id = c.id and i.orden_id = o.orden_id and i.estado = 'CARGADO'),
               'items', coalesce((select jsonb_agg(jsonb_build_object(
                          'id', i.id, 'tipo', i.tipo, 'codigo', i.codigo, 'n', i.n, 'total', i.total,
                          'cajas', i.cajas, 'unidades', i.unidades, 'estado', i.estado,
                          'cargado_por', i.cargado_por, 'cargado_en', i.cargado_en, 'motivo', i.motivo) order by i.n)
                        from wms_carga_items i where i.carga_id = c.id and i.orden_id = o.orden_id), '[]'::jsonb))
             order by o.id)
      from wms_carga_ordenes o join netsuite_ordenes_venta v on v.id = o.orden_id
      where o.carga_id = c.id), '[]'::jsonb));
end $$;

-- Cargas de la bodega (abiertas primero; las cerradas de los últimos días)
create or replace function public.wms_cargas_lista(p_bodega text, p_solo_abiertas boolean default true, p_dias integer default 15)
returns jsonb language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'id', c.id, 'numero', c.numero, 'patente', c.patente, 'contenedor', c.contenedor, 'chofer', c.chofer,
           'destino', c.destino, 'estado', c.estado, 'creado_por', c.creado_por, 'creado_en', c.creado_en,
           'cerrado_por', c.cerrado_por, 'cerrado_en', c.cerrado_en,
           'ordenes', (select string_agg(o.numero_ov, ', ' order by o.id) from wms_carga_ordenes o where o.carga_id = c.id),
           'total', (select count(*) from wms_carga_items i where i.carga_id = c.id and i.estado <> 'QUITADO'),
           'cargados', (select count(*) from wms_carga_items i where i.carga_id = c.id and i.estado = 'CARGADO'),
           'unidades', (select coalesce(sum(i.unidades), 0) from wms_carga_items i where i.carga_id = c.id and i.estado <> 'QUITADO'))
         order by case c.estado when 'ABIERTA' then 0 else 1 end, coalesce(c.cerrado_en, c.creado_en) desc), '[]'::jsonb)
  from wms_cargas c
  where c.bodega = public.wms_bodega_valida(p_bodega)
    and (c.estado = 'ABIERTA'
         or (not coalesce(p_solo_abiertas, true) and coalesce(c.cerrado_en, c.creado_en) > now() - make_interval(days => greatest(coalesce(p_dias, 15), 1))));
$$;

-- =====================================================================
-- Operación de la carga
-- =====================================================================
create or replace function public.wms_carga_crear(p_bodega text, p_patente text, p_contenedor text default null,
                                                  p_chofer text default null, p_destino text default null, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_usuario text := public.wms_usuario_carga(p_usuario);
  v_patente text := upper(regexp_replace(btrim(coalesce(p_patente, '')), '\s+', '', 'g'));
  v_id bigint;
begin
  if length(v_patente) < 4 then raise exception 'WMS: indique la patente del camión (o el número de contenedor)'; end if;
  insert into wms_cargas (bodega, patente, contenedor, chofer, destino, creado_por)
  values (public.wms_bodega_valida(p_bodega), left(v_patente, 20),
          left(nullif(upper(btrim(coalesce(p_contenedor, ''))), ''), 30),
          left(nullif(upper(btrim(coalesce(p_chofer, ''))), ''), 60),
          left(nullif(btrim(coalesce(p_destino, '')), ''), 60), v_usuario)
  returning id into v_id;
  update wms_cargas set numero = 'CG-' || lpad(v_id::text, 6, '0') where id = v_id;
  return public.wms_carga_detalle(v_id);
end $$;

create or replace function public.wms_carga_agregar_orden(p_carga_id bigint, p_numero text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  c record;
  o record;
  d record;
  v_usuario text := public.wms_usuario_carga(p_usuario);
  v_num text := upper(btrim(regexp_replace(coalesce(p_numero, ''), '^\s*OV\s+', '', 'i')));
  v_estado text;
  v_tipo text;
  v_otra text;
  v_base text;
  v_n int;
  v_i int;
  v_agregados int := 0;
  p record;
begin
  select * into c from wms_cargas where id = p_carga_id for update;
  if not found then raise exception 'WMS: la carga % no existe', p_carga_id; end if;
  if c.estado <> 'ABIERTA' then raise exception 'WMS: la carga % está %', c.numero, c.estado; end if;
  if v_num = '' then raise exception 'WMS: escriba el número de la OT u OV'; end if;

  select * into o from netsuite_ordenes_venta v
   where upper(btrim(v.numero_ov)) in (v_num, v_num || '-FA', regexp_replace(v_num, '-FA$', ''))
     and public.wms_bodega_valida(coalesce(v.bodega, 'Bodega Santiago')) = c.bodega
   order by (upper(btrim(v.numero_ov)) = v_num) desc, v.id desc
   limit 1
   for update;
  if not found then raise exception 'WMS: no se encontró la orden % en %', v_num, c.bodega; end if;
  if exists (select 1 from wms_carga_ordenes where carga_id = c.id and orden_id = o.id) then
    raise exception 'WMS: la % ya está en esta carga', o.numero_ov;
  end if;
  v_estado := upper(coalesce(o.estado_ns, o.estado));
  v_tipo := case when public.wms_es_ot_traslado(o.numero_ov) then 'OT' else 'OV' end;

  if v_tipo = 'OT' then
    if v_estado <> 'LISTA_PARA_CARGA'
       and not (v_estado in ('EN_TRANSITO_CCP', 'RECEPCION_CCP_EN_PROCESO') and public.wms_ot_salio_en_carga(o.id)) then
      raise exception 'WMS: la % está % y no se puede cargar%', o.numero_ov, v_estado,
        case when public.wms_orden_estado_ov(v_estado) < 70 then ': termine primero su picking' else ': ya salió de Santiago' end;
    end if;
    insert into wms_carga_ordenes (carga_id, orden_id, numero_ov, tipo, agregado_por)
    values (c.id, o.id, o.numero_ov, 'OT', v_usuario);
    for p in select * from public.wms_ot_pallets_por_cargar(o.id) loop
      select g.numero into v_otra from wms_carga_items i join wms_cargas g on g.id = i.carga_id
       where g.estado = 'ABIERTA' and g.id <> c.id and upper(i.codigo) = p.lpn and i.estado <> 'QUITADO' limit 1;
      continue when v_otra is not null;
      insert into wms_carga_items (carga_id, orden_id, numero_ov, tipo, codigo, cajas, unidades)
      values (c.id, o.id, o.numero_ov, 'PALLET', p.lpn, p.cajas, p.unidades);
      v_agregados := v_agregados + 1;
    end loop;
    if v_agregados = 0 then
      raise exception 'WMS: la % no tiene pallets por cargar%', o.numero_ov,
        coalesce(' (ya están en la carga ' || v_otra || ')', '');
    end if;
  else
    if v_estado in ('ANULADO', 'CERRADO') or public.wms_orden_estado_ov(v_estado) < 70 then
      raise exception 'WMS: la OV % está % : solo se cargan órdenes ya empacadas', o.numero_ov, v_estado;
    end if;
    select g.numero into v_otra from wms_carga_ordenes x join wms_cargas g on g.id = x.carga_id
     where x.orden_id = o.id and g.estado = 'ABIERTA' limit 1;
    if v_otra is not null then raise exception 'WMS: la OV % ya está en la carga %', o.numero_ov, v_otra; end if;
    insert into wms_carga_ordenes (carga_id, orden_id, numero_ov, tipo, agregado_por)
    values (c.id, o.id, o.numero_ov, 'OV', v_usuario);
    select * into d from wms_despacho_ov where orden_id = o.id;
    v_n := greatest(coalesce(d.bultos, 1), 1);
    v_base := coalesce(nullif(upper(btrim(d.lpn)), ''), 'PK-' || replace(upper(btrim(o.numero_ov)), ' ', ''));
    for v_i in 1..v_n loop
      -- un bulto que ya salió en otra carga no se vuelve a cargar
      continue when exists (select 1 from wms_carga_items i join wms_cargas g on g.id = i.carga_id
                             where g.estado = 'CERRADA' and i.orden_id = o.id and i.estado = 'CARGADO'
                               and i.codigo = case when v_n > 1 then v_base || '-B' || v_i else v_base end);
      insert into wms_carga_items (carga_id, orden_id, numero_ov, tipo, codigo, n, total, unidades)
      values (c.id, o.id, o.numero_ov, case when upper(coalesce(d.tipo_empaque, '')) = 'PALLET' then 'PALLET' else 'BULTO' end,
              case when v_n > 1 then v_base || '-B' || v_i else v_base end, v_i, v_n,   -- igual que su etiqueta (bulto 2 de 3)
              case when v_i = 1 then d.unidades end)
      on conflict (carga_id, codigo) do nothing;
      v_agregados := v_agregados + 1;
    end loop;
    if v_agregados = 0 then
      raise exception 'WMS: la OV % ya salió completa en una carga anterior', o.numero_ov;
    end if;
  end if;
  if v_tipo = 'OT' then
    perform public.wms_carga_renumerar(c.id, o.id);
  end if;
  return public.wms_carga_detalle(c.id);
end $$;

create or replace function public.wms_carga_quitar_orden(p_carga_id bigint, p_orden_id bigint, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  c record;
begin
  perform public.wms_usuario_carga(p_usuario);
  select * into c from wms_cargas where id = p_carga_id for update;
  if not found or c.estado <> 'ABIERTA' then raise exception 'WMS: la carga no está abierta'; end if;
  if exists (select 1 from wms_carga_items where carga_id = c.id and orden_id = p_orden_id and estado = 'CARGADO') then
    raise exception 'WMS: esa orden ya tiene pallets/bultos cargados. Desmárquelos antes de sacarla de la carga.';
  end if;
  delete from wms_carga_items where carga_id = c.id and orden_id = p_orden_id;
  delete from wms_carga_ordenes where carga_id = c.id and orden_id = p_orden_id;
  return public.wms_carga_detalle(c.id);
end $$;

-- Escanear un pallet o bulto al subirlo al camión
create or replace function public.wms_carga_escanear(p_carga_id bigint, p_codigo text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  c record;
  i record;
  v_usuario text := public.wms_usuario_carga(p_usuario);
  v_cod text := public.wms_codigo_carga(p_codigo);
  v_ot text;
  v_ya boolean := false;
begin
  select * into c from wms_cargas where id = p_carga_id for update;
  if not found then raise exception 'WMS: la carga % no existe', p_carga_id; end if;
  if c.estado <> 'ABIERTA' then raise exception 'WMS: la carga % está %', c.numero, c.estado; end if;
  if v_cod = '' then raise exception 'WMS: escanee la etiqueta del pallet o bulto'; end if;

  select * into i from wms_carga_items where carga_id = c.id and upper(codigo) = v_cod for update;
  if not found then
    -- el número de la OV escaneado: se marca su siguiente bulto pendiente (etiquetas sin código por bulto)
    select it.* into i from wms_carga_items it
     where it.carga_id = c.id and it.estado = 'PENDIENTE'
       and (upper(it.numero_ov) = v_cod or upper(it.numero_ov) = v_cod || '-FA' or 'OV ' || upper(it.numero_ov) = v_cod)
     order by it.n limit 1 for update;
  end if;
  if not found then
    select p.numero_ov into v_ot from wms_ot_pallets p where upper(p.lpn) = v_cod limit 1;
    if v_ot is not null then
      raise exception 'WMS: el pallet % es de la %, que no está en esta carga. Agréguela primero.', v_cod, v_ot;
    end if;
    raise exception 'WMS: % no es parte de la carga %. Revise la etiqueta.', v_cod, c.numero;
  end if;
  if i.estado = 'CARGADO' then
    v_ya := true;
  else
    update wms_carga_items set estado = 'CARGADO', cargado_por = v_usuario, cargado_en = now(), motivo = null
     where id = i.id;
  end if;
  return jsonb_build_object('ya_cargado', v_ya, 'codigo', i.codigo, 'numero_ov', i.numero_ov, 'tipo', i.tipo,
                            'n', i.n, 'total', i.total, 'carga', public.wms_carga_detalle(c.id));
end $$;

-- Desmarcar (se bajó del camión) o quitar de esta carga (viaja en otra)
create or replace function public.wms_carga_cambiar_item(p_carga_id bigint, p_codigo text, p_accion text,
                                                          p_motivo text default null, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  c record;
  v_usuario text := public.wms_usuario_carga(p_usuario);
  v_accion text := upper(btrim(coalesce(p_accion, '')));
  v_n int;
begin
  select * into c from wms_cargas where id = p_carga_id for update;
  if not found or c.estado <> 'ABIERTA' then raise exception 'WMS: la carga no está abierta'; end if;
  if v_accion = 'DESMARCAR' then
    update wms_carga_items set estado = 'PENDIENTE', cargado_por = null, cargado_en = null, motivo = null
     where carga_id = c.id and upper(codigo) = public.wms_codigo_carga(p_codigo);
  elsif v_accion = 'QUITAR' then
    if length(btrim(coalesce(p_motivo, ''))) < 3 then raise exception 'WMS: indique por qué queda fuera de esta carga'; end if;
    update wms_carga_items set estado = 'QUITADO', cargado_por = v_usuario, cargado_en = now(), motivo = left(btrim(p_motivo), 200)
     where carga_id = c.id and upper(codigo) = public.wms_codigo_carga(p_codigo);
  else
    raise exception 'WMS: acción inválida %', p_accion;
  end if;
  get diagnostics v_n = row_count;
  if v_n = 0 then raise exception 'WMS: % no está en la carga %', p_codigo, c.numero; end if;
  return public.wms_carga_detalle(c.id);
end $$;

-- Cerrar la carga: recién aquí la OT sale de Santiago (EN_TRANSITO_CCP)
create or replace function public.wms_carga_cerrar(p_carga_id bigint, p_motivo_pendientes text default null, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  c record;
  o record;
  v_usuario text := public.wms_usuario_carga(p_usuario);
  v_pend int;
  v_carg int;
  v_lista text;
  v_ots jsonb := '[]'::jsonb;
  v_motivo text := nullif(btrim(coalesce(p_motivo_pendientes, '')), '');
begin
  select * into c from wms_cargas where id = p_carga_id for update;
  if not found then raise exception 'WMS: la carga % no existe', p_carga_id; end if;
  if c.estado <> 'ABIERTA' then raise exception 'WMS: la carga % ya está %', c.numero, c.estado; end if;

  select count(*), string_agg(numero_ov || ' ' || codigo, ', ' order by numero_ov, n) into v_pend, v_lista
    from wms_carga_items where carga_id = c.id and estado = 'PENDIENTE';
  if v_pend > 0 and v_motivo is null then
    raise exception 'WMS: faltan % por subir (%). Para cerrar así indique el motivo: quedan fuera de esta carga.', v_pend, left(v_lista, 300);
  end if;
  update wms_carga_items set estado = 'QUITADO', motivo = v_motivo, cargado_por = v_usuario, cargado_en = now()
   where carga_id = c.id and estado = 'PENDIENTE';
  select count(*) into v_carg from wms_carga_items where carga_id = c.id and estado = 'CARGADO';
  if v_carg = 0 then raise exception 'WMS: la carga % no tiene nada cargado', c.numero; end if;

  update wms_cargas set estado = 'CERRADA', cerrado_por = v_usuario, cerrado_en = now() where id = c.id;

  for o in
    select x.orden_id, x.numero_ov, x.tipo, upper(coalesce(v.estado_ns, v.estado)) estado,
           count(i.id) filter (where i.estado = 'CARGADO') cargados, count(i.id) total
      from wms_carga_ordenes x
      join netsuite_ordenes_venta v on v.id = x.orden_id
      left join wms_carga_items i on i.carga_id = x.carga_id and i.orden_id = x.orden_id
     where x.carga_id = c.id
     group by x.orden_id, x.numero_ov, x.tipo, v.estado_ns, v.estado
  loop
    continue when o.cargados = 0;
    if o.tipo = 'OT' then
      update wms_ot_pallets set estado = 'DESPACHADO'
       where orden_id = o.orden_id
         and upper(lpn) in (select upper(codigo) from wms_carga_items where carga_id = c.id and orden_id = o.orden_id and estado = 'CARGADO');
      if o.estado = 'LISTA_PARA_CARGA' then
        perform public.wms_cambiar_estado_ov(o.orden_id, 'EN_TRANSITO_CCP', v_usuario,
          format('Salió de Santiago en la carga %s (patente %s): %s de %s pallets%s', c.numero, c.patente, o.cargados, o.total,
                 case when (select count(*) from public.wms_ot_pallets_por_cargar(o.orden_id)) > 0
                      then ' · quedan pallets en Santiago' else '' end));
      else
        insert into wms_historial_estados (entidad_tipo, entidad_id, documento, estado_anterior, estado_nuevo, usuario, bodega, observacion)
        values ('ORDEN_VENTA', o.orden_id, o.numero_ov, o.estado, o.estado, v_usuario, c.bodega,
                format('Salieron %s pallets más en la carga %s (patente %s)', o.cargados, c.numero, c.patente));
      end if;
      v_ots := v_ots || jsonb_build_object('numero_ov', o.numero_ov, 'pallets', o.cargados);
    else
      -- OV: solo control de carga, la orden sigue su flujo de facturación y ruteo
      insert into wms_historial_estados (entidad_tipo, entidad_id, documento, estado_anterior, estado_nuevo, usuario, bodega, observacion)
      values ('ORDEN_VENTA', o.orden_id, o.numero_ov, o.estado, o.estado, v_usuario, c.bodega,
              format('Cargada en camión: carga %s, patente %s, %s de %s bultos', c.numero, c.patente, o.cargados, o.total));
    end if;
  end loop;

  return public.wms_carga_detalle(c.id) || jsonb_build_object('ot_en_transito', v_ots);
end $$;

create or replace function public.wms_carga_anular(p_carga_id bigint, p_motivo text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  c record;
  v_usuario text := public.wms_usuario_carga(p_usuario);
begin
  select * into c from wms_cargas where id = p_carga_id for update;
  if not found or c.estado <> 'ABIERTA' then raise exception 'WMS: solo se anula una carga abierta'; end if;
  if length(btrim(coalesce(p_motivo, ''))) < 4 then raise exception 'WMS: escriba el motivo de la anulación'; end if;
  update wms_cargas set estado = 'ANULADA', cerrado_por = v_usuario, cerrado_en = now(),
         observacion = left('ANULADA: ' || btrim(p_motivo), 300)
   where id = c.id;
  return public.wms_carga_detalle(c.id);
end $$;

-- =====================================================================
-- C) OT por cargar y ajustes antes de la carga (PC)
-- =====================================================================
create or replace function public.wms_ot_por_cargar(p_bodega text)
returns jsonb language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'orden_id', o.id, 'numero_ov', o.numero_ov, 'estado', upper(coalesce(o.estado_ns, o.estado)),
           'parcial', upper(coalesce(o.estado_ns, o.estado)) <> 'LISTA_PARA_CARGA',
           'pickeado_por', d.cerrado_por, 'pickeado_en', d.cerrado_en,
           'fotos', (select count(*) from wms_ot_cajas k where k.orden_id = o.id and k.anulado_en is null and k.foto_path is not null),
           'cajas_registradas', (select count(*) from wms_ot_cajas k where k.orden_id = o.id and k.anulado_en is null),
           'pallets', (select coalesce(jsonb_agg(jsonb_build_object(
                          'lpn', p.lpn, 'cajas', p.cajas, 'unidades', p.unidades, 'skus', p.skus,
                          'carga', (select g.numero from wms_carga_items i join wms_cargas g on g.id = i.carga_id
                                     where g.estado = 'ABIERTA' and upper(i.codigo) = p.lpn and i.orden_id = o.id limit 1),
                          'estado_carga', (select i.estado from wms_carga_items i join wms_cargas g on g.id = i.carga_id
                                     where g.estado = 'ABIERTA' and upper(i.codigo) = p.lpn and i.orden_id = o.id limit 1))
                        order by p.lpn), '[]'::jsonb)
                       from public.wms_ot_pallets_por_cargar(o.id) p))
         order by d.cerrado_en nulls last, o.id), '[]'::jsonb)
  from netsuite_ordenes_venta o
  left join wms_despacho_ov d on d.orden_id = o.id
  where public.wms_es_ot_traslado(o.numero_ov)
    and public.wms_bodega_valida(coalesce(o.bodega, 'Bodega Santiago')) = public.wms_bodega_valida(p_bodega)
    and (upper(coalesce(o.estado_ns, o.estado)) = 'LISTA_PARA_CARGA'
         or (upper(coalesce(o.estado_ns, o.estado)) in ('EN_TRANSITO_CCP', 'RECEPCION_CCP_EN_PROCESO')
             and public.wms_ot_salio_en_carga(o.id)
             and exists (select 1 from public.wms_ot_pallets_por_cargar(o.id))));
$$;

-- Cajas de la OT con su foto (registro interno de Santiago)
create or replace function public.wms_ot_cajas_detalle(p_orden_id bigint)
returns jsonb language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'id', k.id, 'lpn', k.lpn, 'id_detalle', k.id_detalle, 'sku', k.sku, 'lote', k.lote,
           'fecha_vencimiento_cl', k.fecha_vencimiento_cl, 'fecha_leida', k.fecha_leida, 'unidades', k.unidades,
           'foto_path', k.foto_path, 'ubicacion', k.ubicacion, 'usuario', k.usuario, 'creado_en', k.creado_en,
           'descripcion', (select m.descripcion from maestra_sku m where upper(m.sku) = public.wms_normalizar_sku(k.sku) limit 1))
         order by k.lpn, k.sku, k.id), '[]'::jsonb)
  from wms_ot_cajas k where k.orden_id = p_orden_id and k.anulado_en is null;
$$;

-- La OT (y sus pallets) se pueden ajustar: está en Santiago y nada de eso va arriba de un camión
create or replace function public.wms_ot_validar_ajuste(p_orden_id bigint, p_lpns text[])
returns public.netsuite_ordenes_venta language plpgsql security definer set search_path = public as $$
declare
  o public.netsuite_ordenes_venta;
  v_estado text;
  v_lpn text;
  v_carga text;
begin
  select * into o from netsuite_ordenes_venta where id = p_orden_id for update;
  if not found then raise exception 'WMS: la orden % no existe', p_orden_id; end if;
  if not public.wms_es_ot_traslado(o.numero_ov) then raise exception 'WMS: % no es una OT', o.numero_ov; end if;
  v_estado := upper(coalesce(o.estado_ns, o.estado));
  if v_estado <> 'LISTA_PARA_CARGA'
     and not (v_estado in ('EN_TRANSITO_CCP', 'RECEPCION_CCP_EN_PROCESO') and public.wms_ot_salio_en_carga(p_orden_id)) then
    raise exception 'WMS: la % está %: solo se ajusta una OT que está lista para carga', o.numero_ov, v_estado;
  end if;
  foreach v_lpn in array coalesce(p_lpns, '{}'::text[]) loop
    if public.wms_ot_salio_en_carga(p_orden_id) and not public.wms_ot_lpn_en_santiago(p_orden_id, v_lpn) then
      raise exception 'WMS: el pallet % ya salió de Santiago', v_lpn;
    end if;
    select g.numero into v_carga from wms_carga_items i join wms_cargas g on g.id = i.carga_id
     where g.estado = 'ABIERTA' and upper(i.codigo) = upper(v_lpn) and i.estado = 'CARGADO' limit 1;
    if v_carga is not null then
      raise exception 'WMS: el pallet % ya está arriba del camión (carga %). Desmárquelo antes de ajustarlo.', v_lpn, v_carga;
    end if;
  end loop;
  return o;
end $$;

-- Rehace el packing list oficial de la OT desde sus cajas (lo que Concepción va a recibir)
create or replace function public.wms_ot_regenerar_packing(p_orden_id bigint)
returns void language plpgsql security definer set search_path = public as $$
declare
  v_detalle jsonb;
  v_pallets int;
  v_pl bigint;
begin
  select packing_list_id into v_pl from wms_despacho_ov where orden_id = p_orden_id;
  if v_pl is null then raise exception 'WMS: la OT no tiene packing list de cierre'; end if;
  select jsonb_agg(jsonb_build_object('id_detalle', z.id_detalle, 'sku', z.sku, 'lote', z.lote,
                                      'fecha_vencimiento_cl', z.venc, 'unidades_totales', z.un, 'cajas', z.n,
                                      'lpn_pallet', z.lpn, 'lpn_consolidado', z.lpn) order by z.lpn, z.sku),
         count(distinct z.lpn)
    into v_detalle, v_pallets
    from (select c.id_detalle, c.sku, c.lote, c.fecha_vencimiento_cl venc, c.lpn, sum(c.unidades) un, count(*) n
            from wms_ot_cajas c where c.orden_id = p_orden_id and c.anulado_en is null
           group by 1, 2, 3, 4, 5) z;
  if coalesce(v_pallets, 0) = 0 then raise exception 'WMS: la OT quedaría sin cajas'; end if;
  update wms_packing_lists_fa set detalle_json = v_detalle where id = v_pl;
  update wms_despacho_ov set bultos = v_pallets,
         lpn = (select min(lpn) from wms_ot_cajas where orden_id = p_orden_id and anulado_en is null)
   where orden_id = p_orden_id;
  update netsuite_detalle_ov d
     set lotes_pickeados = z.traza
    from (select c.id_detalle, string_agg('[' || c.lpn || '] ' || c.lote || ' / ' || coalesce(c.fecha_vencimiento_cl, 'S/F')
                                          || ' (' || c.un || ' UN)', ' | ' order by c.lpn, c.lote) traza
            from (select id_detalle, lpn, lote, fecha_vencimiento_cl, sum(unidades) un
                    from wms_ot_cajas where orden_id = p_orden_id and anulado_en is null group by 1, 2, 3, 4) c
           group by c.id_detalle) z
   where d.id = z.id_detalle and d.orden_id = p_orden_id;
end $$;

-- Mantiene al día los pallets de la OT en las cargas abiertas (tras mover cajas o abrir un pallet nuevo)
create or replace function public.wms_carga_sincronizar_ot(p_orden_id bigint)
returns void language plpgsql security definer set search_path = public as $$
declare
  g record;
  p record;
begin
  for g in select distinct x.carga_id from wms_carga_ordenes x join wms_cargas c on c.id = x.carga_id
            where x.orden_id = p_orden_id and c.estado = 'ABIERTA' loop
    delete from wms_carga_items i
     where i.carga_id = g.carga_id and i.orden_id = p_orden_id and i.estado <> 'CARGADO'
       and not exists (select 1 from public.wms_ot_pallets_por_cargar(p_orden_id) p where p.lpn = upper(i.codigo));
    for p in select * from public.wms_ot_pallets_por_cargar(p_orden_id) loop
      update wms_carga_items set cajas = p.cajas, unidades = p.unidades
       where carga_id = g.carga_id and upper(codigo) = p.lpn;
      if not found and not exists (select 1 from wms_carga_items i join wms_cargas c on c.id = i.carga_id
                                    where c.estado = 'ABIERTA' and upper(i.codigo) = p.lpn) then
        insert into wms_carga_items (carga_id, orden_id, numero_ov, tipo, codigo, cajas, unidades)
        select g.carga_id, p_orden_id, numero_ov, 'PALLET', p.lpn, p.cajas, p.unidades
          from netsuite_ordenes_venta where id = p_orden_id;
      end if;
    end loop;
    perform public.wms_carga_renumerar(g.carga_id, p_orden_id);
  end loop;
end $$;

-- Cambiar lote / vencimiento de cajas ya pickeadas (corrige también el stock de Santiago)
create or replace function public.wms_ot_ajustar_lote(p_caja_ids bigint[], p_lote text, p_vencimiento text,
                                                      p_motivo text, p_usuario text default null, p_mover_stock boolean default true)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o public.netsuite_ordenes_venta;
  k record;
  v_orden bigint;
  v_lpns text[];
  v_usuario text := public.wms_usuario_carga(p_usuario);
  v_lote text := coalesce(nullif(upper(btrim(coalesce(p_lote, ''))), ''), 'S/L');
  v_venc text := nullif(btrim(coalesce(p_vencimiento, '')), '');
  v_ubic text;
  v_sku text;
  v_r jsonb;
  v_faltante int := 0;
  v_cambiadas int := 0;
  v_cambios jsonb := '[]'::jsonb;
begin
  if length(btrim(coalesce(p_motivo, ''))) < 4 then raise exception 'WMS: escriba el motivo del cambio de lote'; end if;
  if coalesce(cardinality(p_caja_ids), 0) = 0 then raise exception 'WMS: elija las cajas a corregir'; end if;
  select min(orden_id), array_agg(distinct lpn) into v_orden, v_lpns
    from wms_ot_cajas where id = any(p_caja_ids) and anulado_en is null;
  if v_orden is null then raise exception 'WMS: las cajas elegidas no existen o están anuladas'; end if;
  if (select count(distinct orden_id) from wms_ot_cajas where id = any(p_caja_ids)) > 1 then
    raise exception 'WMS: las cajas deben ser de una sola OT';
  end if;
  o := public.wms_ot_validar_ajuste(v_orden, v_lpns);

  for k in select * from wms_ot_cajas where id = any(p_caja_ids) and anulado_en is null order by id for update loop
    continue when k.lote = v_lote and coalesce(k.fecha_vencimiento_cl, '') = coalesce(v_venc, '');
    if p_mover_stock and k.lote <> v_lote then
      v_sku := public.wms_normalizar_sku(k.sku);
      if v_sku like '%-FA' then v_sku := left(v_sku, length(v_sku) - 3); end if;
      v_ubic := coalesce(nullif(k.ubicacion, ''), public.wms_picking_fijo_sku(k.bodega, v_sku));
      if v_ubic is not null then
        -- devuelve el lote que se descontó por error y descuenta el lote real
        perform public.wms_sumar_en_ubicacion(k.bodega, v_ubic, v_sku, k.lote, null, k.fecha_vencimiento_cl, 0, k.unidades);
        perform public.wms_kardex(k.bodega, 'AJUSTE_LOTE_OT (' || k.numero_ov || ')', k.lpn, v_sku, k.lote,
                                  'PALLET ' || k.lpn, v_ubic, 0, k.unidades);
        v_r := public.wms_salida_picking(k.bodega, v_sku, v_lote, k.unidades, k.numero_ov || ' AJUSTE LOTE', v_usuario, v_ubic);
        v_faltante := v_faltante + coalesce((v_r->>'faltante')::int, 0);
      end if;
    end if;
    update wms_ot_cajas set lote = v_lote, fecha_vencimiento_cl = v_venc where id = k.id;
    v_cambios := v_cambios || jsonb_build_object('caja', k.id, 'lpn', k.lpn, 'sku', k.sku, 'unidades', k.unidades,
                                                 'antes', k.lote || ' / ' || coalesce(k.fecha_vencimiento_cl, 'S/F'),
                                                 'despues', v_lote || ' / ' || coalesce(v_venc, 'S/F'));
    v_cambiadas := v_cambiadas + 1;
  end loop;
  if v_cambiadas = 0 then raise exception 'WMS: las cajas ya tienen ese lote y vencimiento'; end if;

  perform public.wms_ot_regenerar_packing(o.id);
  perform public.wms_carga_sincronizar_ot(o.id);
  insert into wms_ot_ajustes (orden_id, numero_ov, tipo, detalle, motivo, usuario)
  values (o.id, o.numero_ov, 'CAMBIO_LOTE', jsonb_build_object('cajas', v_cambios, 'stock_sin_registro', v_faltante),
          btrim(p_motivo), v_usuario);
  return jsonb_build_object('cajas', v_cambiadas, 'stock_sin_registro', v_faltante, 'numero_ov', o.numero_ov);
end $$;

-- Mover cajas a otro pallet de la misma OT (o a uno nuevo con su LPN)
create or replace function public.wms_ot_mover_cajas(p_caja_ids bigint[], p_lpn_destino text, p_motivo text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o public.netsuite_ordenes_venta;
  v_orden bigint;
  v_lpns text[];
  v_destino text := nullif(upper(btrim(coalesce(p_lpn_destino, ''))), '');
  v_nuevo boolean := false;
  v_usuario text := public.wms_usuario_carga(p_usuario);
  r jsonb;
  v_n int;
  v_borrados text[];
begin
  if length(btrim(coalesce(p_motivo, ''))) < 4 then raise exception 'WMS: escriba el motivo'; end if;
  select min(orden_id), array_agg(distinct lpn) into v_orden, v_lpns
    from wms_ot_cajas where id = any(p_caja_ids) and anulado_en is null;
  if v_orden is null then raise exception 'WMS: elija las cajas a mover'; end if;
  if (select count(distinct orden_id) from wms_ot_cajas where id = any(p_caja_ids)) > 1 then
    raise exception 'WMS: las cajas deben ser de una sola OT';
  end if;
  o := public.wms_ot_validar_ajuste(v_orden, v_lpns || coalesce(array[v_destino], '{}'::text[]));
  if v_destino is null or v_destino = 'NUEVO' then
    r := public.wms_reservar_lpn(coalesce(o.bodega, 'Bodega Santiago'), 1, v_usuario);
    v_destino := 'LPN-' || (r ->> 'desde');
    insert into wms_ot_pallets (orden_id, numero_ov, bodega, lpn, estado, usuario, cerrado_en)
    values (o.id, o.numero_ov, coalesce(o.bodega, 'Bodega Santiago'), v_destino, 'CERRADO', v_usuario, now());
    v_nuevo := true;
  elsif not exists (select 1 from wms_ot_pallets where orden_id = o.id and upper(lpn) = v_destino) then
    raise exception 'WMS: el pallet % no es de la %', v_destino, o.numero_ov;
  end if;
  update wms_ot_cajas set lpn = v_destino where id = any(p_caja_ids) and anulado_en is null and lpn <> v_destino;
  get diagnostics v_n = row_count;
  with borr as (
    delete from wms_ot_pallets p where p.orden_id = o.id and p.estado <> 'DESPACHADO'
       and not exists (select 1 from wms_ot_cajas c where c.lpn = p.lpn and c.anulado_en is null)
    returning p.lpn)
  select array_agg(lpn) into v_borrados from borr;

  perform public.wms_ot_regenerar_packing(o.id);
  perform public.wms_carga_sincronizar_ot(o.id);
  insert into wms_ot_ajustes (orden_id, numero_ov, tipo, detalle, motivo, usuario)
  values (o.id, o.numero_ov, 'MOVER_CAJAS',
          jsonb_build_object('cajas', to_jsonb(p_caja_ids), 'desde', to_jsonb(v_lpns), 'hacia', v_destino,
                             'pallet_nuevo', v_nuevo, 'pallets_vacios_eliminados', to_jsonb(v_borrados)),
          btrim(p_motivo), v_usuario);
  return jsonb_build_object('lpn_destino', v_destino, 'nuevo', v_nuevo, 'movidas', v_n,
                            'pallets_eliminados', to_jsonb(coalesce(v_borrados, '{}'::text[])),
                            'pallets', public.wms_ot_estado_sin_abrir(o.id));
end $$;

-- Devolver la OT al picking (agregar o quitar cajas). Su último pallet se reabre.
create or replace function public.wms_ot_reabrir_picking(p_orden_id bigint, p_motivo text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o record;
  v_usuario text := public.wms_usuario_carga(p_usuario);
  v_carga text;
  v_res jsonb;
begin
  if length(btrim(coalesce(p_motivo, ''))) < 4 then raise exception 'WMS: escriba el motivo'; end if;
  select * into o from netsuite_ordenes_venta where id = p_orden_id for update;
  if not found then raise exception 'WMS: la orden % no existe', p_orden_id; end if;
  if upper(coalesce(o.estado_ns, o.estado)) <> 'LISTA_PARA_CARGA' then
    raise exception 'WMS: solo se reabre una OT lista para carga (la % está %)', o.numero_ov, coalesce(o.estado_ns, o.estado);
  end if;
  select g.numero into v_carga from wms_carga_items i join wms_cargas g on g.id = i.carga_id
   where i.orden_id = o.id and i.estado = 'CARGADO' and g.estado in ('ABIERTA', 'CERRADA') limit 1;
  if v_carga is not null then
    raise exception 'WMS: la % tiene pallets cargados en la carga %. Desmárquelos antes de reabrirla.', o.numero_ov, v_carga;
  end if;
  delete from wms_carga_items i using wms_cargas g
   where g.id = i.carga_id and g.estado = 'ABIERTA' and i.orden_id = o.id;
  delete from wms_carga_ordenes x using wms_cargas g
   where g.id = x.carga_id and g.estado = 'ABIERTA' and x.orden_id = o.id;
  update wms_ot_pallets set estado = 'ABIERTO', cerrado_en = null
   where id = (select max(id) from wms_ot_pallets where orden_id = o.id);
  v_res := public.wms_cambiar_estado_ov(o.id, 'PENDIENTE_PICKING', v_usuario,
             left('Reabierta a picking antes de la carga: ' || btrim(p_motivo), 500), true);
  insert into wms_ot_ajustes (orden_id, numero_ov, tipo, detalle, motivo, usuario)
  values (o.id, o.numero_ov, 'REABRIR_PICKING', jsonb_build_object('operador', o.operador_asignado), btrim(p_motivo), v_usuario);
  return v_res;
end $$;

create or replace function public.wms_ot_ajustes_lista(p_orden_id bigint)
returns jsonb language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(to_jsonb(a) order by a.creado_en desc), '[]'::jsonb)
  from wms_ot_ajustes a where a.orden_id = p_orden_id;
$$;

-- =====================================================================
-- D) Concepción: pallets que siguen en Santiago
-- =====================================================================
create or replace function public.wms_traslado_ccp_detalle(p_orden_id bigint)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare
  o record;
  v_pallets jsonb;
begin
  select * into o from netsuite_ordenes_venta where id = p_orden_id;
  if not found then raise exception 'WMS: la orden % no existe', p_orden_id; end if;

  select coalesce(jsonb_agg(p order by (p->>'en_santiago')::boolean, (p->>'pendiente')::boolean desc, p->>'lpn'), '[]'::jsonb) into v_pallets
  from (
    select jsonb_build_object(
      'lpn', x.lpn,
      'estado', coalesce(t.estado, 'PENDIENTE'),
      'pendiente', t.id is null or t.estado not in ('RECIBIDO_CCP', 'RECIBIDO_CON_DIFERENCIAS', 'NO_LLEGO'),
      'en_santiago', public.wms_ot_lpn_en_santiago(p_orden_id, x.lpn) and t.id is null,
      'carga', (select concat_ws(' · ', g.numero, g.patente) from wms_carga_items i join wms_cargas g on g.id = i.carga_id
                 where i.orden_id = p_orden_id and upper(i.codigo) = x.lpn and i.estado = 'CARGADO' and g.estado = 'CERRADA'
                 order by g.cerrado_en desc limit 1),
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

-- "Salió de Santiago" = cierre de la carga del camión
CREATE OR REPLACE FUNCTION public.wms_traslados_ccp(p_solo_abiertos boolean DEFAULT true)
 RETURNS TABLE(orden_id bigint, numero_ot text, estado text, despachado_en timestamp with time zone, despachado_por text, pallets integer, pallets_recibidos integer, pallets_no_llegaron integer, unidades_despachadas integer, unidades_recibidas integer, unidades_diferencia integer, pallets_con_diferencia integer, faltante_packing integer, motivo_faltante_packing text, recibido_por text, ultima_recepcion timestamp with time zone)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select o.id::bigint, o.numero_ov, upper(coalesce(o.estado_ns, o.estado)),
         coalesce(cg.cerrado_en, d.cerrado_en), coalesce(cg.texto, d.cerrado_por),
         coalesce(lp.pallets, 0), coalesce(r.recibidos, 0), coalesce(r.no_llegaron, 0),
         coalesce(lp.unidades, 0), coalesce(r.unidades_rec, 0), coalesce(r.dif, 0), coalesce(r.con_dif, 0),
         coalesce(d.faltante_un, 0), d.motivo_faltante,
         r.ultimo_usuario, r.ultima
  from netsuite_ordenes_venta o
  left join wms_despacho_ov d on d.orden_id = o.id
  left join lateral (   -- (40) salida real: la última carga de camión cerrada con pallets de la OT
    select c.cerrado_en, concat_ws(' · ', c.numero, 'patente ' || c.patente, c.cerrado_por) texto
    from wms_cargas c
    where c.estado = 'CERRADA'
      and exists (select 1 from wms_carga_items i where i.carga_id = c.id and i.orden_id = o.id and i.estado = 'CARGADO')
    order by c.cerrado_en desc limit 1
  ) cg on true
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
$function$;


-- Cerrar con pallets que no llegaron: no vale para pallets que siguen en Santiago
CREATE OR REPLACE FUNCTION public.wms_cerrar_recepcion_traslado(p_orden_id bigint, p_usuario text DEFAULT NULL::text, p_motivo text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
  -- (40) Un pallet que todavía no sale de Santiago (no se ha cargado en un camión) no es "no llegó"
  if exists (select 1 from public.wms_traslado_lineas_despachadas(p_orden_id) d
              where public.wms_ot_lpn_en_santiago(p_orden_id, d.lpn)
                and not exists (select 1 from wms_recepcion_traslados_ccp t
                                 where t.orden_id = p_orden_id and upper(t.lpn) = d.lpn
                                   and t.estado in ('RECIBIDO_CCP', 'RECIBIDO_CON_DIFERENCIAS', 'NO_LLEGO'))) then
    raise exception 'WMS: la OT % tiene pallets que todavía están en Santiago (no se han cargado en un camión). Espere esa carga antes de cerrar.', o.numero_ov;
  end if;
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
end $function$;


-- =====================================================================
-- Permisos de ejecución
-- Celular (anon con sesión obligatoria) y PC: operación de la carga.
-- Solo PC (authenticated / service_role): ajustes de la OT y sus fotos.
-- =====================================================================
grant execute on function public.wms_codigo_carga(text) to anon, authenticated, service_role;
grant execute on function public.wms_usuario_carga(text) to anon, authenticated, service_role;
grant execute on function public.wms_ot_lpn_en_santiago(bigint, text) to anon, authenticated, service_role;
grant execute on function public.wms_ot_pallets_por_cargar(bigint) to anon, authenticated, service_role;
grant execute on function public.wms_ot_salio_en_carga(bigint) to anon, authenticated, service_role;
grant execute on function public.wms_carga_detalle(bigint) to anon, authenticated, service_role;
grant execute on function public.wms_cargas_lista(text, boolean, integer) to anon, authenticated, service_role;
grant execute on function public.wms_carga_crear(text, text, text, text, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_carga_agregar_orden(bigint, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_carga_quitar_orden(bigint, bigint, text) to anon, authenticated, service_role;
grant execute on function public.wms_carga_escanear(bigint, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_carga_cambiar_item(bigint, text, text, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_carga_cerrar(bigint, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_carga_anular(bigint, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_traslado_ccp_detalle(bigint) to anon, authenticated, service_role;

revoke execute on function public.wms_carga_renumerar(bigint, bigint) from public, anon;
revoke execute on function public.wms_carga_sincronizar_ot(bigint) from public, anon;
revoke execute on function public.wms_ot_regenerar_packing(bigint) from public, anon;
revoke execute on function public.wms_ot_validar_ajuste(bigint, text[]) from public, anon;
revoke execute on function public.wms_ot_por_cargar(text) from public, anon;
revoke execute on function public.wms_ot_cajas_detalle(bigint) from public, anon;
revoke execute on function public.wms_ot_ajustar_lote(bigint[], text, text, text, text, boolean) from public, anon;
revoke execute on function public.wms_ot_mover_cajas(bigint[], text, text, text) from public, anon;
revoke execute on function public.wms_ot_reabrir_picking(bigint, text, text) from public, anon;
revoke execute on function public.wms_ot_ajustes_lista(bigint) from public, anon;
grant execute on function public.wms_ot_por_cargar(text) to authenticated, service_role;
grant execute on function public.wms_ot_cajas_detalle(bigint) to authenticated, service_role;
grant execute on function public.wms_ot_ajustar_lote(bigint[], text, text, text, text, boolean) to authenticated, service_role;
grant execute on function public.wms_ot_mover_cajas(bigint[], text, text, text) to authenticated, service_role;
grant execute on function public.wms_ot_reabrir_picking(bigint, text, text) to authenticated, service_role;
grant execute on function public.wms_ot_ajustes_lista(bigint) to authenticated, service_role;
grant execute on function public.wms_carga_sincronizar_ot(bigint) to service_role;
grant execute on function public.wms_carga_renumerar(bigint, bigint) to service_role;
grant execute on function public.wms_ot_regenerar_packing(bigint) to service_role;
grant execute on function public.wms_ot_validar_ajuste(bigint, text[]) to service_role;

-- =====================================================================
-- E) Módulos y permisos
-- =====================================================================
insert into public.wms_modulos_app (codigo, plataforma, nombre, descripcion, orden, indice_app, reemplaza) values
  ('APP_PICKING_OT',    'RF', 'Picking OT (traslados)', 'OT a Concepción: foto de la fecha y pallets LPN', 56, 12, '{RF_PICKING}'),
  ('APP_CARGA_CAMION',  'RF', 'Carga de camión',        'Subir pallets y bultos de OT/OV al camión',        62, 13, '{RF_PICKING}'),
  ('PC_CARGAS',         'PC', 'Cargas de camión (OT)',  null, 45, null, '{}')
on conflict (codigo) do update
  set plataforma = excluded.plataforma, nombre = excluded.nombre, descripcion = excluded.descripcion,
      orden = excluded.orden, indice_app = excluded.indice_app, reemplaza = excluded.reemplaza;
update public.wms_modulos_app set descripcion = 'Órdenes -FA de farmacia (las OT tienen su propio módulo)'
 where codigo = 'APP_PICKING_FARMACIA';

-- Nadie pierde acceso: Picking farmacia -> también Picking OT; Packing -> también Carga de camión
update public.wms_usuarios u
   set modulos_rf = (select array(select distinct x from unnest(u.modulos_rf
                        || case when 'APP_PICKING_FARMACIA' = any(u.modulos_rf) then array['APP_PICKING_OT'] else '{}'::text[] end
                        || case when 'APP_PACKING' = any(u.modulos_rf) then array['APP_CARGA_CAMION'] else '{}'::text[] end) x order by x))
 where u.modulos_rf && array['APP_PICKING_FARMACIA', 'APP_PACKING'];
do $$ begin
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'wms_usuarios' and column_name = 'modulos_pc') then
    execute $q$
      update public.wms_usuarios u
         set modulos_pc = (select array(select distinct x from unnest(u.modulos_pc || array['PC_CARGAS']) x order by x))
       where 'PC_OLAS' = any(u.modulos_pc) and not ('PC_CARGAS' = any(u.modulos_pc))$q$;
  end if;
exception when others then
  raise notice 'modulos_pc no actualizado: %', sqlerrm;
end $$;

commit;

-- Revisión
select 'OT listas para carga' as que, count(*) from public.netsuite_ordenes_venta where upper(coalesce(estado_ns, estado)) = 'LISTA_PARA_CARGA'
union all
select 'Cargas abiertas', count(*) from public.wms_cargas where estado = 'ABIERTA';
