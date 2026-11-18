begin;
create table if not exists public.wms_catalogo_estados (
  codigo text primary key,
  modulo text not null,
  descripcion text not null,
  orden_flujo integer not null default 0,
  es_final boolean not null default false,
  color_hex text not null default '#64748B',
  activo boolean not null default true
);
create table if not exists public.wms_historial_estados (
  id bigserial primary key,
  entidad_tipo text not null,
  entidad_id bigint null,
  documento text null,
  estado_anterior text null,
  estado_nuevo text not null references public.wms_catalogo_estados(codigo),
  usuario text null,
  bodega text null,
  observacion text null,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
insert into public.wms_catalogo_estados(codigo,modulo,descripcion,orden_flujo,es_final,color_hex) values
('PENDIENTE_PICKING','SALIDA','Pendiente de Picking',10,false,'#F59E0B'),
('PICKING_EN_PROCESO','SALIDA','Picking en proceso',20,false,'#0284C7'),
('PICKING_COMPLETO','SALIDA','Picking completo',30,false,'#0EA5E9'),
('PENDIENTE_PACKING','SALIDA','Pendiente de Packing',40,false,'#F59E0B'),
('PACKING_EN_PROCESO','SALIDA','Packing en proceso',50,false,'#7C3AED'),
('PACKING_COMPLETO','SALIDA','Packing completo',60,false,'#059669'),
('EN_TRANSITO_CCP','TRASLADO','En tránsito a Concepción',70,false,'#0F766E'),
('RECEPCION_CCP_EN_PROCESO','TRASLADO','Recepción CCP en proceso',80,false,'#0284C7'),
('RECIBIDO_CCP','TRASLADO','Recibido conforme en CCP',90,true,'#047857'),
('RECIBIDO_CCP_CON_DIFERENCIAS','TRASLADO','Recibido en CCP con diferencias',90,true,'#B45309'),
('PENDIENTE_RECEPCION','ENTRADA','Pendiente de recepción',10,false,'#F59E0B'),
('RECEPCION_EN_PROCESO','ENTRADA','Recepción en proceso',20,false,'#0284C7'),
('RECIBIDO_CONFORME','ENTRADA','Recibido conforme',30,false,'#047857'),
('RECIBIDO_CON_DIFERENCIAS','ENTRADA','Recibido con diferencias',30,false,'#B45309'),
('PENDIENTE_PUTAWAY','ENTRADA','Pendiente Putaway',40,false,'#7C3AED'),
('UBICADO','ENTRADA','Ubicado',50,true,'#047857')
on conflict(codigo) do update set descripcion=excluded.descripcion, modulo=excluded.modulo;
create index if not exists idx_historial_estados_entidad on public.wms_historial_estados(entidad_tipo,entidad_id,created_at desc);
commit;
