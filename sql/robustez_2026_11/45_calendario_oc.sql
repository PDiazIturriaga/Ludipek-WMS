-- =====================================================================
-- LUDIPEK WMS · 45 CALENDARIO DE OC (NetSuite) Y TIEMPOS DE RECEPCIÓN   (requiere 33)
--
-- · wms_oc_netsuite: copia de las órdenes de compra de NetSuite (la llena el PC con
--   "Actualizar desde NetSuite" en Recepción › Calendario de OC; no se edita a mano).
-- · asn_cabecera.cerrada_en: momento en que la OC se cerró en el WMS (estado COMPLETADO).
-- · wms_oc_calendario(desde, hasta): cada OC con sus fechas y los tiempos:
--     creada en NetSuite → llegó (primer pallet recibido) → cerrada en el WMS,
--     y contra la fecha esperada de NetSuite (atraso).
--   También detecta cuando la mercadería llegó ANTES de que existiera la OC (recepción sin OC
--   conciliada después).
-- =====================================================================
begin;

create table if not exists public.wms_oc_netsuite (
  numero_oc       text primary key,          -- tranid de NetSuite, normalizado (sin "OC")
  ns_id           bigint,
  tranid          text,
  proveedor       text,
  ubicacion       text,
  estado_ns       text,
  fecha_oc        date,                      -- fecha del documento (trandate)
  creada_en       timestamptz,               -- cuándo la crearon en NetSuite (createddate)
  fecha_esperada  date,                      -- "Recibir antes de" de NetSuite (duedate)
  unidades        numeric,
  lineas          integer,
  nota            text,
  vista_primera_vez timestamptz not null default now(),
  sincronizada_en timestamptz not null default now()
);
create index if not exists idx_oc_ns_creada on public.wms_oc_netsuite (creada_en);
create index if not exists idx_oc_ns_fecha on public.wms_oc_netsuite (fecha_oc);
alter table public.wms_oc_netsuite enable row level security;
revoke all on public.wms_oc_netsuite from anon, authenticated;
grant select, insert, update, delete on public.wms_oc_netsuite to service_role;
do $$ begin
  if to_regprocedure('public.wms_pc_autorizado()') is not null then
    execute 'drop policy if exists wms_pc_sesion on public.wms_oc_netsuite';
    execute 'create policy wms_pc_sesion on public.wms_oc_netsuite for select to authenticated using ((select public.wms_pc_autorizado()))';
    execute 'grant select on public.wms_oc_netsuite to authenticated';
  end if;
end $$;

-- Número de OC comparable entre NetSuite y el WMS ("OC2043", "oc-2043", "2043" -> "2043")
create or replace function public.wms_numero_oc(p text)
returns text language sql immutable as $$
  select nullif(regexp_replace(upper(btrim(coalesce(p, ''))), '^(OC|PO)[\s\-#]*', ''), '');
$$;

-- Cierre de la OC en el WMS con su hora (antes solo cambiaba el estado)
alter table public.asn_cabecera add column if not exists cerrada_en timestamptz;
create or replace function public.wms_asn_marcar_cierre()
returns trigger language plpgsql as $$
begin
  if upper(coalesce(new.estado, '')) in ('COMPLETADO', 'CERRADO', 'CERRADA')
     and upper(coalesce(old.estado, '')) not in ('COMPLETADO', 'CERRADO', 'CERRADA') then
    new.cerrada_en := coalesce(new.cerrada_en, now());
  elsif upper(coalesce(new.estado, '')) not in ('COMPLETADO', 'CERRADO', 'CERRADA') then
    new.cerrada_en := null;                -- reabierta
  end if;
  return new;
end $$;
drop trigger if exists trg_asn_marcar_cierre on public.asn_cabecera;
create trigger trg_asn_marcar_cierre before update of estado on public.asn_cabecera
  for each row execute function public.wms_asn_marcar_cierre();

-- OC ya cerradas antes de este script: se toma la hora de su última recepción
update public.asn_cabecera a
   set cerrada_en = z.ultima
  from (select asn_id, max(coalesce(fecha_recepcion, created_at)) ultima
          from public.registro_recepcion where asn_id is not null group by asn_id) z
 where z.asn_id = a.id and a.cerrada_en is null
   and upper(coalesce(a.estado, '')) in ('COMPLETADO', 'CERRADO', 'CERRADA');

-- Guardar lo leído de NetSuite (lo llama el PC)
create or replace function public.wms_oc_sincronizar(p_filas jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_n int := 0;
  v_nuevas int := 0;
  f jsonb;
  v_num text;
begin
  for f in select * from jsonb_array_elements(coalesce(p_filas, '[]'::jsonb)) loop
    v_num := public.wms_numero_oc(f->>'tranid');
    continue when v_num is null;
    if not exists (select 1 from wms_oc_netsuite where numero_oc = v_num) then v_nuevas := v_nuevas + 1; end if;
    insert into wms_oc_netsuite (numero_oc, ns_id, tranid, proveedor, ubicacion, estado_ns, fecha_oc, creada_en,
                                 fecha_esperada, unidades, lineas, nota)
    values (v_num, nullif(f->>'ns_id', '')::bigint, f->>'tranid', f->>'proveedor', f->>'ubicacion', f->>'estado_ns',
            nullif(f->>'fecha_oc', '')::date,
            -- NetSuite entrega la hora de creación en hora de Chile
            (nullif(f->>'creada_en', '')::timestamp at time zone 'America/Santiago'),
            nullif(f->>'fecha_esperada', '')::date, nullif(f->>'unidades', '')::numeric,
            nullif(f->>'lineas', '')::int, left(f->>'nota', 300))
    on conflict (numero_oc) do update
      set ns_id = excluded.ns_id, tranid = excluded.tranid, proveedor = excluded.proveedor,
          ubicacion = excluded.ubicacion, estado_ns = excluded.estado_ns, fecha_oc = excluded.fecha_oc,
          creada_en = coalesce(excluded.creada_en, wms_oc_netsuite.creada_en),
          fecha_esperada = excluded.fecha_esperada,
          unidades = coalesce(excluded.unidades, wms_oc_netsuite.unidades),
          lineas = coalesce(excluded.lineas, wms_oc_netsuite.lineas),
          nota = excluded.nota, sincronizada_en = now();
    v_n := v_n + 1;
  end loop;
  return jsonb_build_object('leidas', v_n, 'nuevas', v_nuevas,
                            'ultima_sincronizacion', (select max(sincronizada_en) from wms_oc_netsuite));
end $$;

-- Calendario: OC de NetSuite (y las del WMS que no estén en la copia) con sus tiempos
create or replace function public.wms_oc_calendario(p_desde date, p_hasta date)
returns jsonb language sql stable security definer set search_path = public as $$
  with wms as (   -- lo que el WMS sabe de cada OC
    select public.wms_numero_oc(a.numero_oc) numero_oc,
           min(a.created_at) cargada_wms_en,
           max(a.cerrada_en) cerrada_en,
           bool_and(upper(coalesce(a.estado, '')) in ('COMPLETADO', 'CERRADO', 'CERRADA')) cerrada,
           string_agg(distinct a.bodega, ', ') bodega,
           string_agg(distinct a.proveedor, ', ') proveedor,
           min(nullif(a.fecha_documento, '')) fecha_documento,
           array_agg(a.id) asn_ids
      from asn_cabecera a
     where public.wms_numero_oc(a.numero_oc) is not null
     group by 1
  ), rec as (
    select w.numero_oc,
           min(coalesce(r.fecha_recepcion, r.created_at)) llego_en,
           max(coalesce(r.fecha_recepcion, r.created_at)) ultima_recepcion,
           sum(r.unidades_totales) unidades_recibidas,
           count(distinct r.lpn) pallets
      from wms w join registro_recepcion r on r.asn_id = any(w.asn_ids)
     group by 1
  ), sin_oc as (  -- recepciones hechas sin OC y conciliadas después
    select w.numero_oc, min(c.creado_en) conciliada_en
      from wms w join wms_conciliaciones_recepcion c on c.asn_id = any(w.asn_ids) and c.deshecho_en is null
     group by 1
  ), base as (
    select coalesce(n.numero_oc, w.numero_oc) numero_oc,
           coalesce(n.tranid, w.numero_oc) tranid,
           coalesce(n.proveedor, w.proveedor) proveedor,
           n.ubicacion, n.estado_ns, n.fecha_oc, n.fecha_esperada, n.unidades unidades_oc,
           coalesce(n.creada_en, (n.fecha_oc::timestamp at time zone 'America/Santiago')) creada_en,
           (n.numero_oc is not null) en_netsuite,
           w.cargada_wms_en, w.cerrada_en, coalesce(w.cerrada, false) cerrada, w.bodega,
           r.llego_en, r.ultima_recepcion, r.unidades_recibidas, r.pallets, s.conciliada_en
      from wms_oc_netsuite n
      full join wms w on w.numero_oc = n.numero_oc
      left join rec r on r.numero_oc = coalesce(n.numero_oc, w.numero_oc)
      left join sin_oc s on s.numero_oc = coalesce(n.numero_oc, w.numero_oc)
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'numero_oc', b.numero_oc, 'tranid', b.tranid, 'proveedor', b.proveedor, 'ubicacion', b.ubicacion,
           'bodega', b.bodega, 'estado_ns', b.estado_ns, 'en_netsuite', b.en_netsuite,
           'fecha_oc', b.fecha_oc, 'creada_en', b.creada_en, 'fecha_esperada', b.fecha_esperada,
           'cargada_wms_en', b.cargada_wms_en, 'llego_en', b.llego_en, 'ultima_recepcion', b.ultima_recepcion,
           'cerrada_en', b.cerrada_en, 'cerrada', b.cerrada,
           'unidades_oc', b.unidades_oc, 'unidades_recibidas', b.unidades_recibidas, 'pallets', b.pallets,
           'llego_antes_de_oc', b.llego_en is not null and b.creada_en is not null and b.llego_en < b.creada_en,
           'conciliada_en', b.conciliada_en,
           'dias_creacion_a_llegada', round((extract(epoch from (b.llego_en - b.creada_en)) / 86400.0)::numeric, 1),
           'dias_llegada_a_cierre', round((extract(epoch from (b.cerrada_en - b.llego_en)) / 86400.0)::numeric, 1),
           'dias_creacion_a_cierre', round((extract(epoch from (b.cerrada_en - b.creada_en)) / 86400.0)::numeric, 1),
           'dias_atraso', case when b.fecha_esperada is null then null
                               when b.llego_en is not null then ((b.llego_en at time zone 'America/Santiago')::date - b.fecha_esperada)
                               when (now() at time zone 'America/Santiago')::date > b.fecha_esperada
                                    then (now() at time zone 'America/Santiago')::date - b.fecha_esperada end,
           'estado', case when b.cerrada then 'CERRADA'
                          when b.llego_en is not null then 'RECIBIENDO'
                          when b.fecha_esperada is not null
                               and b.fecha_esperada < (now() at time zone 'America/Santiago')::date then 'ATRASADA'
                          else 'POR_LLEGAR' end)
         order by b.creada_en nulls last, b.numero_oc), '[]'::jsonb)
  from base b
  where (b.creada_en at time zone 'America/Santiago')::date between p_desde and p_hasta
     or b.fecha_esperada between p_desde and p_hasta
     or (b.llego_en at time zone 'America/Santiago')::date between p_desde and p_hasta
     or (b.creada_en is null and (b.cargada_wms_en at time zone 'America/Santiago')::date between p_desde and p_hasta);
$$;

create or replace function public.wms_oc_ultima_sincronizacion()
returns timestamptz language sql stable security definer set search_path = public as $$
  select max(sincronizada_en) from wms_oc_netsuite;
$$;

revoke execute on function public.wms_oc_sincronizar(jsonb) from public, anon;
revoke execute on function public.wms_oc_calendario(date, date) from public, anon;
revoke execute on function public.wms_oc_ultima_sincronizacion() from public, anon;
grant execute on function public.wms_oc_sincronizar(jsonb) to authenticated, service_role;
grant execute on function public.wms_oc_calendario(date, date) to authenticated, service_role;
grant execute on function public.wms_oc_ultima_sincronizacion() to authenticated, service_role;
grant execute on function public.wms_numero_oc(text) to anon, authenticated, service_role;

commit;

select 'OC en la copia de NetSuite' as que, count(*) from public.wms_oc_netsuite
union all
select 'OC cerradas con hora de cierre', count(*) from public.asn_cabecera where cerrada_en is not null;
