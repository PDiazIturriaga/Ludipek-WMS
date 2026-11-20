-- =====================================================================
-- LUDIPEK WMS · 31 CATÁLOGO DE MÓDULOS (PC Y CELULAR) PARA LOS PERMISOS
-- El PC (Admin > Usuarios y Accesos) arma las casillas de permisos desde esta tabla.
-- Cada módulo nuevo que se cree en el celular o en el PC se agrega aquí (un insert)
-- y aparece solo en la pantalla de permisos.
--
-- Celular: antes había 6 permisos gruesos (ej. RF_PICKING abría picking normal, picking
-- farmacia y packing; RF_INVENTARIO abría stock, vacías y conteo por SKU). Ahora hay un
-- permiso por cada módulo de la app (códigos APP_...). Los usuarios actuales NO pierden
-- nada: este script les agrega los permisos nuevos equivalentes a los que ya tenían.
-- =====================================================================
begin;

create table if not exists public.wms_modulos_app (
  codigo       text primary key,
  plataforma   text not null check (plataforma in ('RF', 'PC')),
  nombre       text not null,
  descripcion  text,
  orden        integer not null default 100,
  indice_app   integer,                 -- número de módulo dentro de main.dart (celular)
  reemplaza    text[] not null default '{}',   -- permisos antiguos que equivalen a este
  activo       boolean not null default true,
  creado_en    timestamptz not null default now()
);
alter table public.wms_modulos_app enable row level security;
drop policy if exists leer_modulos_app on public.wms_modulos_app;
create policy leer_modulos_app on public.wms_modulos_app for select to anon, authenticated using (true);
grant select on public.wms_modulos_app to anon, authenticated;
grant select, insert, update, delete on public.wms_modulos_app to service_role;

insert into public.wms_modulos_app (codigo, plataforma, nombre, descripcion, orden, indice_app, reemplaza) values
  -- Celular (app RF)
  ('APP_RECEPCION',         'RF', 'Recepción en andén',            'OC, lectura GS1 y LPN',                           10, 0,  '{RF_RECEPCION}'),
  ('APP_TRASLADOS',         'RF', 'Recibir traslados (Concepción)', 'Pallets OT-CCP que llegan desde Santiago',       15, 10, '{RF_RECEPCION,RF_TRASLADOS}'),
  ('APP_MAESTRA',           'RF', 'Maestra y enrolamiento',         'Enrolar EAN, medidas y peso de productos',        20, 4,  '{RF_RECEPCION}'),
  ('APP_ALMACENAMIENTO',    'RF', 'Almacenamiento',                 'Guardar LPN en ubicación',                        30, 1,  '{RF_PUTAWAY}'),
  ('APP_REABASTECIMIENTO',  'RF', 'Movimiento a picking',           'Bajar pallets de reserva a picking (FEFO)',       40, 2,  '{RF_REABASTECIMIENTO}'),
  ('APP_PICKING',           'RF', 'Picking normal',                 'Órdenes de venta normales',                       50, 9,  '{RF_PICKING}'),
  ('APP_PICKING_FARMACIA',  'RF', 'Picking farmacia',               'Órdenes -FA y OT de traslado',                    55, 5,  '{RF_PICKING}'),
  ('APP_PACKING',           'RF', 'Packing y despacho',             'Mesas de packing, bultos y pallets',              60, 8,  '{RF_PICKING}'),
  ('APP_STOCK_CONTEO',      'RF', 'Stock y conteo cíclico',         'Consulta por ubicación/LPN y conteo por pasillo', 70, 3,  '{RF_CONSULTA,RF_INVENTARIO}'),
  ('APP_VACIAS',            'RF', 'Ubicaciones vacías',             'Auditoría de espacios vacíos',                    75, 6,  '{RF_INVENTARIO}'),
  ('APP_CICLICO_SKU',       'RF', 'Conteo por SKU',                 'Conteo cíclico dirigido por producto',            80, 7,  '{RF_INVENTARIO}'),
  ('APP_CONSULTA_STOCK',    'RF', 'Consulta de stock',              '¿Queda stock? Dónde está cada producto',          90, 11,
     '{RF_RECEPCION,RF_PUTAWAY,RF_PICKING,RF_REABASTECIMIENTO,RF_INVENTARIO,RF_CONSULTA}'),
  -- PC (torre de control)
  ('PC_DASHBOARD',          'PC', 'Dashboards & BI',                     null, 10, null, '{}'),
  ('PC_RECEPCION',          'PC', 'Recepción (Ingresos PO)',             null, 20, null, '{}'),
  ('PC_ALMACENAMIENTO',     'PC', 'Almacenamiento (Putaway)',            null, 30, null, '{}'),
  ('PC_OLAS',               'PC', 'Olas & Packing',                      null, 40, null, '{}'),
  ('PC_INVENTARIO',         'PC', 'Mov. Stock (Inventario)',             null, 50, null, '{}'),
  ('PC_ADMIN_MAESTRA',      'PC', 'Admin. Usuarios & Maestra SKU',       null, 60, null, '{}'),
  ('PC_RUTEO',              'PC', 'Ruteo y Facturación',                 null, 70, null, '{}'),
  ('PC_IMPRESION',          'PC', 'Etiquetas & Impresión',               null, 80, null, '{}'),
  ('PC_RECEPCION_CCP',      'PC', 'Recepción Traslados Concepción',      null, 90, null, '{}')
on conflict (codigo) do update
  set plataforma = excluded.plataforma, nombre = excluded.nombre, descripcion = excluded.descripcion,
      orden = excluded.orden, indice_app = excluded.indice_app, reemplaza = excluded.reemplaza;

-- Usuarios actuales: agregar los permisos APP_ equivalentes a los antiguos (sin quitar nada)
update public.wms_usuarios u
   set modulos_rf = (
         select array(select distinct x from unnest(
                  coalesce(u.modulos_rf, '{}') ||
                  coalesce((select array_agg(m.codigo) from public.wms_modulos_app m
                             where m.plataforma = 'RF' and m.reemplaza && coalesce(u.modulos_rf, '{}')), '{}')) x
                order by x))
 where coalesce(cardinality(u.modulos_rf), 0) > 0
   and not exists (select 1 from unnest(u.modulos_rf) p where p like 'APP\_%');

commit;

-- Revisión
select plataforma, orden, codigo, nombre, indice_app from public.wms_modulos_app order by plataforma desc, orden;

-- Para agregar un módulo nuevo en el futuro (aparece solo en la pantalla de permisos):
-- insert into public.wms_modulos_app (codigo, plataforma, nombre, descripcion, orden, indice_app)
-- values ('APP_NUEVO', 'RF', 'Nombre visible', 'Para qué sirve', 95, 12);
