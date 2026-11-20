-- =====================================================================
-- LUDIPEK WMS · 96 REVERTIR 36 (PC CON SESIÓN)  — solo si el PC con llave pública diera problemas
-- Deja todo como antes del 36: los PC vuelven a necesitar la llave maestra en su .env.
-- (Las tablas wms_usuarios, wms_sesiones y wms_config siguen cerradas a la llave pública:
--  el celular no las usa directo, así que eso no se revierte.)
-- =====================================================================
begin;

-- 1. Quitar las políticas de sesión PC
do $$
declare p record;
begin
  for p in select tablename, policyname from pg_policies
            where schemaname = 'public' and policyname in ('wms_pc_sesion', 'wms_pc_sesion_admin') loop
    execute format('drop policy %I on public.%I', p.policyname, p.tablename);
  end loop;
end $$;

-- 2. Las funciones solo-PC vuelven a ser solo de la llave maestra
do $$
declare f record;
begin
  for f in select p.oid::regprocedure sig from pg_proc p
            where p.pronamespace = 'public'::regnamespace and p.prokind = 'f'
              and not has_function_privilege('anon', p.oid, 'EXECUTE')
              and has_function_privilege('authenticated', p.oid, 'EXECUTE') loop
    execute format('revoke execute on function %s from authenticated', f.sig);
  end loop;
end $$;

-- 3. Portero como en el script 24
create or replace function public.wms_pre_request()
returns void language plpgsql stable security definer set search_path = public as $$
declare
  v_path text;
begin
  if public.wms_rol_peticion() not in ('anon', 'authenticated') then
    return;
  end if;
  if not public.wms_auth_obligatoria() then
    return;
  end if;
  v_path := coalesce(current_setting('request.path', true), '');
  if v_path ~ '/rpc/(wms_login|wms_iniciar_sesion|wms_cerrar_sesion|wms_version_minima)$' then
    return;
  end if;
  if public.wms_sesion_usuario() is null then
    raise exception 'WMS: SESION_EXPIRADA: vuelva a iniciar sesión' using errcode = '42501';
  end if;
end $$;

-- 4. Cerrar las sesiones de PC abiertas
update public.wms_sesiones set cerrada_en = now() where tipo = 'PC' and cerrada_en is null;

drop function if exists public.wms_iniciar_sesion_pc(text, text, text);
drop function if exists public.wms_pc_permiso(text);
drop function if exists public.wms_funcion_solo_pc(text);
drop function if exists public.wms_pc_autorizado();
commit;

notify pgrst, 'reload config';
notify pgrst, 'reload schema';
