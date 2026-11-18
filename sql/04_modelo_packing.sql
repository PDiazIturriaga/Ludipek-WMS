begin;
create table if not exists public.wms_packing_cabecera (
 id bigserial primary key,
 orden_id bigint not null references public.netsuite_ordenes_venta(id) on delete cascade,
 numero_ov text not null,
 estado text not null references public.wms_catalogo_estados(codigo),
 bodega text not null,
 usuario text null,
 version integer not null default 1,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create unique index if not exists uq_packing_activo_orden on public.wms_packing_cabecera(orden_id) where estado='PACKING_EN_PROCESO';
create table if not exists public.wms_packing_pallet (
 id bigserial primary key,
 packing_id bigint not null references public.wms_packing_cabecera(id) on delete cascade,
 lpn text not null unique,
 estado text not null default 'ABIERTO',
 cerrado_at timestamptz null,
 created_at timestamptz not null default now()
);
create table if not exists public.wms_packing_linea (
 id bigserial primary key,
 pallet_id bigint not null references public.wms_packing_pallet(id) on delete cascade,
 detalle_orden_id bigint not null references public.netsuite_detalle_ov(id),
 sku text not null,
 lote text not null default 'S/L',
 fecha_vencimiento date null,
 cajas integer not null default 0 check(cajas>=0),
 displays integer not null default 0 check(displays>=0),
 unidades_sueltas integer not null default 0 check(unidades_sueltas>=0),
 multiplo_caja integer not null default 1 check(multiplo_caja>=1),
 multiplo_display integer not null default 1 check(multiplo_display>=1),
 unidades_totales integer not null check(unidades_totales>0),
 created_at timestamptz not null default now(),
 unique(pallet_id,detalle_orden_id,lote,fecha_vencimiento)
);
create index if not exists idx_packing_pallet_packing on public.wms_packing_pallet(packing_id,id);
create index if not exists idx_packing_linea_detalle on public.wms_packing_linea(detalle_orden_id);
create index if not exists idx_packing_linea_sku_lote on public.wms_packing_linea(sku,lote,fecha_vencimiento);
commit;
