begin;
alter table public.asn_detalle add column if not exists unidades_oc integer;
alter table public.asn_detalle add column if not exists unidades_packing_list integer;
alter table public.asn_detalle add column if not exists cajas_oc integer;
alter table public.asn_detalle add column if not exists cajas_packing_list integer;
update public.asn_detalle set unidades_oc=coalesce(unidades_oc,unidades_esperadas), cajas_oc=coalesce(cajas_oc,cajas_esperadas)
where unidades_oc is null or cajas_oc is null;
create table if not exists public.asn_packing_list_detalle (
 id bigserial primary key,
 asn_id bigint not null references public.asn_cabecera(id) on delete cascade,
 asn_detalle_id bigint null references public.asn_detalle(id) on delete cascade,
 sku text not null,
 descripcion text null,
 lote text not null default 'S/L',
 fecha_vencimiento date null,
 cajas integer not null default 0 check(cajas>=0),
 displays integer not null default 0 check(displays>=0),
 unidades_sueltas integer not null default 0 check(unidades_sueltas>=0),
 unidades_totales integer not null check(unidades_totales>=0),
 documento_origen text null,
 created_at timestamptz not null default now(),
 unique(asn_id,sku,lote,fecha_vencimiento,documento_origen)
);
create index if not exists idx_asn_pl_detalle_asn_sku on public.asn_packing_list_detalle(asn_id,sku);
create index if not exists idx_registro_recepcion_trazabilidad on public.registro_recepcion(asn_id,lpn,sku,lote,fecha_vencimiento);
commit;
