-- =====================================================================
-- LUDIPEK WMS · 69 PERFILES DE USUARIO CON MÓDULOS PRECARGADOS  (requiere 31 y 36)
-- Admin › Usuarios: al crear un usuario se elige un PERFIL y se marcan solos el rol y los
-- módulos de PC y celular de ese perfil (se pueden ajustar antes de guardar).
--   · wms_perfiles_usuario: perfiles editables (desde el PC: "Guardar módulos en el perfil").
--   · wms_usuarios.perfil: perfil con que se creó o editó cada usuario.
-- Los perfiles iniciales se cargan solo si no existen: volver a ejecutar NO pisa los cambios.
-- El módulo Desarrollador no va en ningún perfil: se marca a mano.
-- =====================================================================
begin;

create table if not exists public.wms_perfiles_usuario (
  codigo          text primary key,
  nombre          text not null,
  descripcion     text,
  rol             text not null,
  modulos_pc      text[] not null default '{}',
  modulos_rf      text[] not null default '{}',
  orden           integer not null default 100,
  activo          boolean not null default true,
  actualizado_en  timestamptz not null default now(),
  actualizado_por text
);

alter table public.wms_perfiles_usuario enable row level security;
drop policy if exists wms_pc_sesion on public.wms_perfiles_usuario;
create policy wms_pc_sesion on public.wms_perfiles_usuario for select to authenticated
  using ((select public.wms_pc_autorizado()));
drop policy if exists wms_pc_sesion_admin on public.wms_perfiles_usuario;
create policy wms_pc_sesion_admin on public.wms_perfiles_usuario for all to authenticated
  using ((select public.wms_pc_permiso('PC_ADMIN_MAESTRA'))) with check ((select public.wms_pc_permiso('PC_ADMIN_MAESTRA')));
grant select, insert, update, delete on public.wms_perfiles_usuario to authenticated, service_role;

alter table public.wms_usuarios add column if not exists perfil text;

-- Perfiles iniciales
insert into public.wms_perfiles_usuario (codigo, nombre, descripcion, rol, modulos_pc, modulos_rf, orden)
values
 ('ADMINISTRADOR', 'Administrador', 'Acceso total (sin Desarrollador)', 'ADMIN',
  array(select codigo from public.wms_modulos_app where plataforma = 'PC' and activo and codigo <> 'PC_DESARROLLADOR' order by orden),
  array(select codigo from public.wms_modulos_app where plataforma = 'RF' and activo order by orden), 10),
 ('SUPERVISOR', 'Supervisor de bodega', 'Toda la operación en PC y celular, sin administrar usuarios', 'SUPERVISOR',
  array(select codigo from public.wms_modulos_app where plataforma = 'PC' and activo
          and codigo not in ('PC_DESARROLLADOR', 'PC_ADMIN_MAESTRA') order by orden),
  array(select codigo from public.wms_modulos_app where plataforma = 'RF' and activo order by orden), 20),
 ('ADMIN_RECEPCION', 'Administrativo de recepción', 'OC, actas, correos y carga en NetSuite', 'SUPERVISOR',
  array['PC_DASHBOARD', 'PC_RECEPCION', 'PC_RECEPCION_CCP', 'PC_IMPRESION'],
  array['APP_CONSULTA_STOCK'], 30),
 ('OPERADOR_RECEPCION', 'Operador de recepción', 'Recibir en andén, almacenar y traslados', 'OPERADOR RF',
  '{}', array['APP_RECEPCION', 'APP_TRASLADOS', 'APP_ALMACENAMIENTO', 'APP_CONSULTA_STOCK'], 40),
 ('OPERADOR_ALMACENAMIENTO', 'Operador de almacenamiento y reposición', 'Guardar pallets y bajar a picking', 'OPERADOR RF',
  '{}', array['APP_ALMACENAMIENTO', 'APP_REABASTECIMIENTO', 'APP_VACIAS', 'APP_CONSULTA_STOCK'], 50),
 ('PICKER', 'Picker', 'Picking normal, OT y farmacia', 'OPERADOR RF',
  '{}', array['APP_PICKING', 'APP_PICKING_OT', 'APP_PICKING_FARMACIA', 'APP_CONSULTA_STOCK'], 60),
 ('PACKING_DESPACHO', 'Packing y despacho', 'Packing, carga de camión y exportación', 'OPERADOR RF',
  array['PC_CARGAS', 'PC_DESPACHOS', 'PC_IMPRESION'],
  array['APP_PACKING', 'APP_CARGA_CAMION', 'APP_DESPACHO_EXPORT', 'APP_CONSULTA_STOCK'], 70),
 ('INVENTARIO', 'Control de inventario', 'Conteos cíclicos, vacías y movimientos de stock', 'AUDITOR',
  array['PC_INVENTARIO', 'PC_ALMACENAMIENTO', 'PC_DASHBOARD'],
  array['APP_CICLICO_SKU', 'APP_STOCK_CONTEO', 'APP_VACIAS', 'APP_CONSULTA_STOCK'], 80),
 ('CONSULTA', 'Consulta (compras, comercial, finanzas)', 'Ver qué llega, stock y bodega', 'CONSULTA',
  array['PC_DASHBOARD', 'PC_RECEPCION', 'PC_ALMACENAMIENTO'],
  '{}', 90)
on conflict (codigo) do nothing;

commit;

-- Revisión
select orden, codigo, nombre, rol, array_length(modulos_pc, 1) as mod_pc, array_length(modulos_rf, 1) as mod_celular
from public.wms_perfiles_usuario order by orden;

-- FIN 69
