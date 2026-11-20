-- =====================================================================
-- LUDIPEK WMS · 36 EL PC TRABAJA CON SESIÓN DE USUARIO (SIN LLAVE MAESTRA)  (requiere 24 y 35)
--
-- Hoy el programa del PC usa la llave service_role, que salta toda la seguridad: quien copie
-- el .env de un PC tiene acceso total a la base. Con este script el PC puede trabajar igual
-- que el celular: con la llave PÚBLICA y una sesión verificada por usuario y contraseña.
--
-- Cómo queda:
--   · wms_iniciar_sesion_pc(): valida usuario/contraseña, exige que el usuario tenga acceso
--     al PC (ADMIN, SUPERVISOR o algún módulo PC marcado) y abre una sesión tipo PC.
--   · Cada tabla recibe una política "wms_pc_sesion": una sesión de PC vigente puede leer y
--     escribir (lo mismo que hoy). El celular NO gana nada: sus sesiones son tipo RF.
--   · wms_usuarios: solo ADMIN o quien tenga "Admin. Usuarios & Maestra SKU" puede modificarla.
--   · wms_usuarios, wms_sesiones y wms_config se cierran a la llave pública (el celular las usa
--     solo a través de funciones; nadie con la URL de la app puede leer los hash de contraseña).
--   · Funciones que hoy son solo del PC (las que el celular no puede ejecutar): quedan
--     disponibles para sesiones de PC y bloqueadas para cualquier otra (portero wms_pre_request).
--   · Lo que corre con la llave maestra (PC antiguo, SQL Editor) sigue funcionando igual.
--
-- Es gradual: cada PC pasa a sesión cuando en su .env la llave SUPABASE_KEY se reemplaza por
-- la pública (ver GUIA_RESPALDO_Y_PRUEBAS.md). Los demás siguen como antes.
-- Requiere "Allow anonymous sign-ins" activado (ya lo usa el celular).
-- =====================================================================
begin;

-- ---------------------------------------------------------------------
-- 1. Sesión de PC
-- ---------------------------------------------------------------------
alter table public.wms_sesiones add column if not exists tipo text not null default 'RF';

-- ¿La petición viene de una sesión de PC vigente?
create or replace function public.wms_pc_autorizado()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1
      from wms_sesiones s join wms_usuarios u on u.id = s.usuario_id
     where s.auth_uid = auth.uid() and s.tipo = 'PC' and s.cerrada_en is null
       and s.creada_en > now() - make_interval(hours => coalesce(
             (select nullif(valor, '')::int from wms_config where clave = 'sesion_horas_pc'), 14))
       and coalesce(u.activo, true));
$$;

-- ¿El usuario de la sesión PC tiene este permiso? (ADMIN o lista vacía = todo, como en el PC)
create or replace function public.wms_pc_permiso(p_codigo text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1
      from wms_sesiones s join wms_usuarios u on u.id = s.usuario_id
     where s.auth_uid = auth.uid() and s.tipo = 'PC' and s.cerrada_en is null
       and coalesce(u.activo, true)
       and (upper(coalesce(u.rol, '')) like '%ADMIN%' or coalesce(cardinality(u.modulos_pc), 0) = 0
            or upper(p_codigo) = any (select upper(x) from unnest(u.modulos_pc) x)))
    and public.wms_pc_autorizado();
$$;

create or replace function public.wms_iniciar_sesion_pc(p_usuario text, p_password text, p_equipo text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_res jsonb;
  v_rol text;
  v_pc text[];
begin
  if v_uid is null then
    raise exception 'WMS: SIN_SESION_SUPABASE: active "Allow anonymous sign-ins" en Supabase';
  end if;
  v_res := public.wms_login(p_usuario, p_password);
  if v_res is null or v_res ? 'error' then
    return v_res;
  end if;
  v_rol := upper(coalesce(v_res ->> 'rol', ''));
  select coalesce(modulos_pc, '{}') into v_pc from wms_usuarios where id = (v_res ->> 'id')::bigint;
  if not (v_rol like '%ADMIN%' or v_rol like '%SUPERV%' or cardinality(v_pc) > 0) then
    raise exception 'WMS: su usuario no tiene módulos del PC habilitados. Pida acceso a un administrador.';
  end if;
  insert into wms_sesiones (auth_uid, usuario_id, usuario, nombre, rol, bodega, dispositivo, tipo, creada_en, ultimo_uso, cerrada_en)
  values (v_uid, (v_res ->> 'id')::bigint, upper(btrim(v_res ->> 'usuario')), v_res ->> 'nombre_completo',
          v_res ->> 'rol', v_res ->> 'bodega', left(nullif(btrim(coalesce(p_equipo, '')), ''), 80), 'PC', now(), now(), null)
  on conflict (auth_uid) do update
    set usuario_id = excluded.usuario_id, usuario = excluded.usuario, nombre = excluded.nombre, rol = excluded.rol,
        bodega = excluded.bodega, dispositivo = excluded.dispositivo, tipo = 'PC',
        creada_en = now(), ultimo_uso = now(), cerrada_en = null;
  return v_res || jsonb_build_object('sesion_verificada', true, 'tipo', 'PC');
end $$;

-- El celular: su sesión siempre queda como RF (aunque mande otro dispositivo)
create or replace function public.wms_iniciar_sesion(p_usuario text, p_password text, p_dispositivo text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_res jsonb;
begin
  if v_uid is null then
    raise exception 'WMS: SIN_SESION_SUPABASE: active "Allow anonymous sign-ins" en Supabase';
  end if;
  v_res := public.wms_login(p_usuario, p_password);
  if v_res is null or v_res ? 'error' then
    return v_res;
  end if;
  insert into wms_sesiones (auth_uid, usuario_id, usuario, nombre, rol, bodega, dispositivo, tipo, creada_en, ultimo_uso, cerrada_en)
  values (v_uid, (v_res ->> 'id')::bigint, upper(btrim(v_res ->> 'usuario')), v_res ->> 'nombre_completo',
          v_res ->> 'rol', v_res ->> 'bodega', left(nullif(btrim(coalesce(p_dispositivo, '')), ''), 80), 'RF', now(), now(), null)
  on conflict (auth_uid) do update
    set usuario_id = excluded.usuario_id, usuario = excluded.usuario, nombre = excluded.nombre, rol = excluded.rol,
        bodega = excluded.bodega, dispositivo = excluded.dispositivo, tipo = 'RF',
        creada_en = now(), ultimo_uso = now(), cerrada_en = null;
  return v_res || jsonb_build_object('sesion_verificada', true);
end $$;

-- El PC informa al entrar cómo se conecta (Salud del sistema avisa de los que siguen con la llave maestra)
create or replace function public.wms_registrar_conexion_pc(p_usuario text, p_equipo text, p_modo text,
                                                            p_ambiente text default null, p_version text default null)
returns void language sql security definer set search_path = public as $$
  insert into wms_pc_conexiones (usuario, equipo, modo, ambiente, version)
  values (left(upper(btrim(coalesce(p_usuario, ''))), 60), left(coalesce(p_equipo, ''), 80),
          case when upper(coalesce(p_modo, '')) = 'SESION' then 'SESION' else 'LLAVE_MAESTRA' end,
          left(coalesce(p_ambiente, ''), 20), left(coalesce(p_version, ''), 30));
  delete from wms_pc_conexiones where creado_en < now() - interval '90 days';
$$;

-- ---------------------------------------------------------------------
-- 2. Políticas: una sesión de PC vigente trabaja sobre todas las tablas
-- ---------------------------------------------------------------------
do $$
declare
  t record;
begin
  for t in
    select c.relname, c.relrowsecurity rls, has_table_privilege('anon', c.oid, 'SELECT,INSERT,UPDATE,DELETE') anon_puede
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind in ('r', 'p')
  loop
    -- Tabla sin RLS que el celular no usa (anon sin permisos): se protege con RLS.
    -- Tabla sin RLS que anon sí usa: se deja como está (ya está abierta; el diagnóstico la informa).
    if not t.rls and not t.anon_puede then
      execute format('alter table public.%I enable row level security', t.relname);
    end if;
    execute format('drop policy if exists wms_pc_sesion on public.%I', t.relname);
    if t.relname = 'wms_usuarios' then
      -- Todos los PC leen usuarios (listas de operadores); solo admin/maestra los modifica
      execute 'create policy wms_pc_sesion on public.wms_usuarios for select to authenticated using ((select public.wms_pc_autorizado()))';
      execute 'drop policy if exists wms_pc_sesion_admin on public.wms_usuarios';
      execute 'create policy wms_pc_sesion_admin on public.wms_usuarios for all to authenticated
                 using ((select public.wms_pc_permiso(''PC_ADMIN_MAESTRA''))) with check ((select public.wms_pc_permiso(''PC_ADMIN_MAESTRA'')))';
    else
      execute format('create policy wms_pc_sesion on public.%I for all to authenticated
                        using ((select public.wms_pc_autorizado())) with check ((select public.wms_pc_autorizado()))', t.relname);
    end if;
    execute format('grant select, insert, update, delete on public.%I to authenticated', t.relname);
  end loop;
end $$;
grant usage, select on all sequences in schema public to authenticated;

-- Tablas sensibles que el celular nunca lee directo (usa funciones): se cierran a la llave pública.
-- wms_usuarios guarda los hash de contraseña; wms_sesiones y wms_config controlan el acceso.
do $$
declare
  t text;
  p record;
begin
  foreach t in array array['wms_usuarios', 'wms_sesiones', 'wms_config'] loop
    if to_regclass('public.' || t) is null then continue; end if;
    execute format('alter table public.%I enable row level security', t);
    for p in select policyname from pg_policies
              where schemaname = 'public' and tablename = t and policyname not like 'wms_pc_sesion%' loop
      execute format('drop policy %I on public.%I', p.policyname, t);
    end loop;
    execute format('revoke all on public.%I from anon', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------
-- 3. Funciones solo-PC: ejecutables por sesiones de PC, bloqueadas para el resto
--    Regla: una función que el celular (anon) NO puede ejecutar es "solo PC". El portero
--    exige sesión de PC para llamarla. Para crear funciones nuevas solo-PC basta con
--    revocarlas a anon (como siempre) y darlas a authenticated.
-- ---------------------------------------------------------------------
create or replace function public.wms_funcion_solo_pc(p_nombre text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = p_nombre)
     and not exists (select 1 from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = p_nombre
                        and has_function_privilege('anon', p.oid, 'EXECUTE'));
$$;

do $$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure sig
      from pg_proc p
     where p.pronamespace = 'public'::regnamespace and p.prokind = 'f'
       and not has_function_privilege('anon', p.oid, 'EXECUTE')
       and not has_function_privilege('authenticated', p.oid, 'EXECUTE')
       and p.prorettype <> 'trigger'::regtype
  loop
    execute format('grant execute on function %s to authenticated', f.sig);
  end loop;
end $$;

-- Portero (reemplaza el del script 24, conserva su lógica de sesión obligatoria)
create or replace function public.wms_pre_request()
returns void language plpgsql stable security definer set search_path = public as $$
declare
  v_path text;
  v_fn text;
begin
  if public.wms_rol_peticion() not in ('anon', 'authenticated') then
    return;                                         -- llave maestra y SQL Editor: sin control
  end if;
  v_path := coalesce(current_setting('request.path', true), '');
  v_fn := substring(v_path from '/rpc/([A-Za-z0-9_]+)$');

  -- a) Funciones solo-PC: exigen sesión de PC vigente
  if v_fn is not null and public.wms_funcion_solo_pc(v_fn) then
    if not public.wms_pc_autorizado() then
      raise exception 'WMS: SESION_PC_REQUERIDA: esta acción es solo del PC con sesión iniciada' using errcode = '42501';
    end if;
    if v_fn in ('wms_cambiar_password', 'wms_cerrar_sesiones_usuario') and not public.wms_pc_permiso('PC_ADMIN_MAESTRA') then
      raise exception 'WMS: solo un administrador de usuarios puede hacer esto' using errcode = '42501';
    end if;
    return;
  end if;

  -- b) Sesión obligatoria para el celular (script 24)
  if not public.wms_auth_obligatoria() then
    return;
  end if;
  if v_fn in ('wms_login', 'wms_iniciar_sesion', 'wms_iniciar_sesion_pc', 'wms_cerrar_sesion', 'wms_version_minima',
              'wms_registrar_error') then
    return;
  end if;
  if public.wms_sesion_usuario() is null then
    raise exception 'WMS: SESION_EXPIRADA: vuelva a iniciar sesión' using errcode = '42501';
  end if;
end $$;

-- wms_sesion_usuario debe reconocer también sesiones de PC (ya lo hace: no filtra por tipo)

grant execute on function public.wms_pc_autorizado() to anon, authenticated, service_role;
grant execute on function public.wms_pc_permiso(text) to authenticated, service_role;
grant execute on function public.wms_funcion_solo_pc(text) to anon, authenticated, service_role;
grant execute on function public.wms_pre_request() to anon, authenticated, service_role;
grant execute on function public.wms_iniciar_sesion_pc(text, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_iniciar_sesion(text, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_registrar_conexion_pc(text, text, text, text, text) to anon, authenticated, service_role;
revoke all on function public.wms_pc_permiso(text) from public, anon;

commit;

-- Instalar / recargar el portero (imprescindible: sin él, las funciones solo-PC quedarían abiertas
-- a cualquier sesión autenticada)
alter role authenticator set pgrst.db_pre_request to 'public.wms_pre_request';
notify pgrst, 'reload config';

-- Revisión 1: el portero debe aparecer aquí
select rolname, rolconfig from pg_roles where rolname = 'authenticator';
-- Revisión 2: usuarios que podrán entrar al PC con sesión (ADMIN, SUPERVISOR o con módulos PC)
select usuario, rol, modulos_pc,
       (upper(coalesce(rol, '')) like '%ADMIN%' or upper(coalesce(rol, '')) like '%SUPERV%'
        or coalesce(cardinality(modulos_pc), 0) > 0) as puede_entrar_pc
  from public.wms_usuarios where coalesce(activo, true) order by 4, 1;
