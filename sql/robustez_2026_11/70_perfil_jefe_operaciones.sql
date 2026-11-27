-- =====================================================================
-- LUDIPEK WMS · 70 PERFIL "JEFE DE OPERACIONES"  (requiere 69)
-- Rol ADMIN OPERACIONES: como contiene ADMIN, tiene las atribuciones de administrador en el
-- PC y en la base (anular OV, dar de baja pallets, administrar usuarios, ver ambas bodegas,
-- ajustes de recepción), con todos los módulos de PC y celular, salvo Desarrollador
-- (errores, tickets, salud del sistema y respaldos), que sigue siendo solo a mano.
-- Además, un usuario puede tener varios perfiles: wms_usuarios.perfil guarda "A+B".
-- Se puede ejecutar más de una vez (no pisa el perfil si ya existe).
-- =====================================================================
begin;

insert into public.wms_perfiles_usuario (codigo, nombre, descripcion, rol, modulos_pc, modulos_rf, orden)
values ('JEFE_OPERACIONES', 'Jefe de operaciones',
        'Toda la operación y la administración de usuarios; sin Desarrollador', 'ADMIN OPERACIONES',
        array(select codigo from public.wms_modulos_app where plataforma = 'PC' and activo and codigo <> 'PC_DESARROLLADOR' order by orden),
        array(select codigo from public.wms_modulos_app where plataforma = 'RF' and activo order by orden), 15)
on conflict (codigo) do nothing;

commit;

-- Revisión
select orden, codigo, nombre, rol, array_length(modulos_pc, 1) as mod_pc, array_length(modulos_rf, 1) as mod_celular
from public.wms_perfiles_usuario order by orden;

-- FIN 70
