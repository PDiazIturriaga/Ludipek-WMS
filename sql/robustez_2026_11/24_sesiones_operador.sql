-- =====================================================================
-- LUDIPEK WMS · 24 SESIÓN DE OPERADOR VERIFICADA POR EL SERVIDOR  (requiere 04, 12, 16 y 21)
--
-- Hasta ahora el celular decía "soy JUAN" en cada llamada y la base le creía.
-- Desde este script:
--   · Al iniciar sesión, el celular obtiene una sesión de Supabase (anónima, por dispositivo)
--     y wms_iniciar_sesion la VINCULA al operador después de validar su contraseña.
--   · Todas las funciones que registran movimientos (wms_contexto) usan el operador de esa
--     sesión, no el nombre que manda el celular. El kardex queda con el usuario real.
--   · Admin (dar de baja pallets) y depurar duplicados también usan el operador de la sesión.
--   · Un "portero" (db_pre_request) revisa cada llamada del celular. Funciona en dos modos
--     (wms_config.auth_modo):
--       OPCIONAL     (por defecto) -> deja pasar como hoy; sirve mientras todos actualizan la app.
--       OBLIGATORIO  -> sin sesión vinculada solo se puede iniciar sesión; todo lo demás se
--                       rechaza (SESION_EXPIRADA). Quien tenga la clave pública ya no puede
--                       leer ni escribir nada.
--   · La sesión dura un turno (wms_config.sesion_horas, 14 h por defecto).
-- El PC usa la clave de servicio: no le afecta nada de esto.
--
-- REQUISITO en Supabase: Authentication > Sign In / Providers > "Allow anonymous sign-ins" activado
-- (la Visión IA de recepción ya lo usa).
--
-- PASO A PASO
--   1) Ejecutar este script (queda en OPCIONAL: no cambia nada para los operadores).
--   2) Publicar main.dart 2026.11.20.1 y subir version_minima_rf a esa versión.
--   3) Cuando todos hayan vuelto a entrar, revisar la consulta del final: cada operador
--      del día debe tener sesión vinculada.
--   4) Activar:  update public.wms_config set valor = 'OBLIGATORIO' where clave = 'auth_modo';
--      Volver atrás en cualquier momento: ... set valor = 'OPCIONAL' ...
-- =====================================================================
begin;

create table if not exists public.wms_sesiones (
  auth_uid    uuid primary key,
  usuario_id  bigint not null references public.wms_usuarios(id) on delete cascade,
  usuario     text not null,
  nombre      text,
  rol         text,
  bodega      text,
  dispositivo text,
  creada_en   timestamptz not null default now(),
  ultimo_uso  timestamptz not null default now(),
  cerrada_en  timestamptz
);
alter table public.wms_sesiones enable row level security;   -- sin políticas: solo funciones y PC
create index if not exists idx_wms_sesiones_usuario on public.wms_sesiones (usuario_id, creada_en desc);
revoke all on public.wms_sesiones from anon, authenticated;

insert into public.wms_config (clave, valor, descripcion) values
  ('auth_modo', 'OPCIONAL', 'OPCIONAL = el celular puede operar sin sesión vinculada (transición). OBLIGATORIO = exige sesión.'),
  ('sesion_horas', '14', 'Horas que dura la sesión de un operador en el celular antes de pedir la contraseña otra vez.')
on conflict (clave) do nothing;

-- ---------------------------------------------------------------------
-- Quién llama
-- ---------------------------------------------------------------------
-- Rol de la petición: anon / authenticated (celular), service_role (PC), '' (SQL Editor)
create or replace function public.wms_rol_peticion()
returns text language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '');
$$;

-- Operador vinculado a la sesión de Supabase de esta petición (null si no hay)
create or replace function public.wms_sesion_usuario()
returns text language sql stable security definer set search_path = public as $$
  select s.usuario
  from wms_sesiones s
  where s.auth_uid = auth.uid()
    and s.cerrada_en is null
    and s.creada_en > now() - make_interval(hours => coalesce(
          (select nullif(valor, '')::int from wms_config where clave = 'sesion_horas'), 14))
  limit 1;
$$;

create or replace function public.wms_auth_obligatoria()
returns boolean language sql stable security definer set search_path = public as $$
  select coalesce((select upper(valor) from wms_config where clave = 'auth_modo'), 'OPCIONAL') = 'OBLIGATORIO';
$$;

-- Usuario con el que se registra la operación:
--   celular con sesión -> el operador de la sesión (se ignora lo que mande el celular)
--   celular sin sesión -> OPCIONAL: lo que mande · OBLIGATORIO: error SESION_EXPIRADA
--   PC / SQL Editor    -> lo que mande
create or replace function public.wms_usuario_efectivo(p_usuario text)
returns text language plpgsql stable security definer set search_path = public as $$
declare
  v_ses text;
begin
  if public.wms_rol_peticion() in ('anon', 'authenticated') then
    v_ses := public.wms_sesion_usuario();
    if v_ses is not null then
      return v_ses;
    end if;
    if public.wms_auth_obligatoria() then
      raise exception 'WMS: SESION_EXPIRADA: vuelva a iniciar sesión' using errcode = '42501';
    end if;
  end if;
  return coalesce(nullif(upper(btrim(coalesce(p_usuario, ''))), ''), 'APP');
end $$;

-- wms_contexto (script 04) ahora usa el usuario verificado
create or replace function public.wms_contexto(p_usuario text, p_origen text)
returns text language plpgsql as $$
declare
  v_usuario text := public.wms_usuario_efectivo(p_usuario);
begin
  perform set_config('wms.usuario', v_usuario, true);
  perform set_config('wms.origen', p_origen, true);
  if public.wms_rol_peticion() in ('anon', 'authenticated') and auth.uid() is not null then
    begin
      update public.wms_sesiones set ultimo_uso = now()
       where auth_uid = auth.uid() and ultimo_uso < now() - interval '2 minutes';
    exception when others then
      null;   -- nunca bloquear una operación por esto
    end;
  end if;
  return v_usuario;
end $$;
revoke all on function public.wms_contexto(text, text) from public, anon, authenticated;

-- ---------------------------------------------------------------------
-- Iniciar / cerrar sesión desde el celular
-- ---------------------------------------------------------------------
create or replace function public.wms_iniciar_sesion(p_usuario text, p_password text, p_dispositivo text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_res jsonb;
begin
  if v_uid is null then
    raise exception 'WMS: SIN_SESION_SUPABASE: active "Allow anonymous sign-ins" en Supabase';
  end if;
  v_res := public.wms_login(p_usuario, p_password);          -- valida la contraseña (bcrypt)
  if v_res is null or v_res ? 'error' then
    return v_res;                                             -- null = credenciales incorrectas
  end if;
  insert into wms_sesiones (auth_uid, usuario_id, usuario, nombre, rol, bodega, dispositivo, creada_en, ultimo_uso, cerrada_en)
  values (v_uid, (v_res ->> 'id')::bigint, upper(btrim(v_res ->> 'usuario')), v_res ->> 'nombre_completo',
          v_res ->> 'rol', v_res ->> 'bodega', left(nullif(btrim(coalesce(p_dispositivo, '')), ''), 80), now(), now(), null)
  on conflict (auth_uid) do update
    set usuario_id = excluded.usuario_id, usuario = excluded.usuario, nombre = excluded.nombre, rol = excluded.rol,
        bodega = excluded.bodega, dispositivo = excluded.dispositivo, creada_en = now(), ultimo_uso = now(), cerrada_en = null;
  return v_res || jsonb_build_object('sesion_verificada', true);
end $$;

create or replace function public.wms_cerrar_sesion()
returns void language sql security definer set search_path = public as $$
  update wms_sesiones set cerrada_en = now() where auth_uid = auth.uid() and cerrada_en is null;
$$;

-- El PC puede cerrar la sesión de un operador (ej. celular perdido o usuario desactivado)
create or replace function public.wms_cerrar_sesiones_usuario(p_usuario text)
returns integer language plpgsql security definer set search_path = public as $$
declare v_n int;
begin
  update wms_sesiones set cerrada_en = now()
   where upper(usuario) = upper(btrim(coalesce(p_usuario, ''))) and cerrada_en is null;
  get diagnostics v_n = row_count;
  return v_n;
end $$;

-- Al desactivar un usuario se cierran sus sesiones
create or replace function public.wms_trg_cerrar_sesiones_inactivo()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if coalesce(new.activo, true) = false and coalesce(old.activo, true) = true then
    update wms_sesiones set cerrada_en = now() where usuario_id = new.id and cerrada_en is null;
  end if;
  return new;
end $$;
drop trigger if exists trg_cerrar_sesiones_inactivo on public.wms_usuarios;
create trigger trg_cerrar_sesiones_inactivo after update of activo on public.wms_usuarios
  for each row execute function public.wms_trg_cerrar_sesiones_inactivo();

-- ---------------------------------------------------------------------
-- Permisos que dependían del nombre enviado por el celular
-- ---------------------------------------------------------------------
create or replace function public.wms_es_admin(p_usuario text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from wms_usuarios u
    where coalesce(u.activo, true)
      and upper(coalesce(u.rol, '')) like '%ADMIN%'
      and public.wms_usuario_efectivo(p_usuario) in (upper(btrim(coalesce(u.usuario, ''))), upper(btrim(coalesce(u.nombre_completo, ''))))
      and btrim(coalesce(p_usuario, '')) <> '');
$$;

create or replace function public.wms_puede_depurar_stock(p_usuario text)
returns boolean language sql stable security definer set search_path = public as $$
  select public.wms_usuario_efectivo(p_usuario) = any (
           string_to_array(replace(upper(coalesce((select valor from wms_config where clave = 'usuarios_depuran_stock'), '')), ' ', ''), ','))
         and public.wms_usuario_efectivo(p_usuario) <> 'APP';
$$;

-- ---------------------------------------------------------------------
-- Portero de la API (se ejecuta antes de CADA llamada del celular)
-- ---------------------------------------------------------------------
create or replace function public.wms_pre_request()
returns void language plpgsql stable security definer set search_path = public as $$
declare
  v_path text;
begin
  if public.wms_rol_peticion() not in ('anon', 'authenticated') then
    return;                                         -- PC (service_role) y SQL Editor: sin control
  end if;
  if not public.wms_auth_obligatoria() then
    return;                                         -- modo OPCIONAL
  end if;
  v_path := coalesce(current_setting('request.path', true), '');
  if v_path ~ '/rpc/(wms_login|wms_iniciar_sesion|wms_cerrar_sesion|wms_version_minima)$' then
    return;                                         -- lo único permitido sin sesión
  end if;
  if public.wms_sesion_usuario() is null then
    raise exception 'WMS: SESION_EXPIRADA: vuelva a iniciar sesión' using errcode = '42501';
  end if;
end $$;

grant execute on function public.wms_rol_peticion() to anon, authenticated, service_role;
grant execute on function public.wms_sesion_usuario() to anon, authenticated, service_role;
grant execute on function public.wms_auth_obligatoria() to anon, authenticated, service_role;
grant execute on function public.wms_usuario_efectivo(text) to anon, authenticated, service_role;
grant execute on function public.wms_pre_request() to anon, authenticated, service_role;
grant execute on function public.wms_iniciar_sesion(text, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_cerrar_sesion() to anon, authenticated, service_role;
revoke all on function public.wms_cerrar_sesiones_usuario(text) from public, anon, authenticated;
grant execute on function public.wms_cerrar_sesiones_usuario(text) to service_role;
revoke all on function public.wms_es_admin(text) from public, anon, authenticated;
grant execute on function public.wms_es_admin(text) to service_role;

commit;

-- Instalar el portero (en OPCIONAL no hace nada; se activa con auth_modo = OBLIGATORIO)
alter role authenticator set pgrst.db_pre_request to 'public.wms_pre_request';
notify pgrst, 'reload config';

-- Revisión: sesiones de hoy por operador
select s.usuario, s.nombre, s.dispositivo,
       to_char(s.creada_en at time zone 'America/Santiago', 'DD-MM HH24:MI') as inicio,
       to_char(s.ultimo_uso at time zone 'America/Santiago', 'DD-MM HH24:MI') as ultimo_uso,
       case when s.cerrada_en is not null then 'CERRADA'
            when s.creada_en < now() - interval '14 hours' then 'VENCIDA' else 'ACTIVA' end as estado,
       (select valor from public.wms_config where clave = 'auth_modo') as modo
from public.wms_sesiones s
where s.creada_en > now() - interval '24 hours'
order by s.ultimo_uso desc;

-- DESINSTALAR EL PORTERO (si algo fallara):
-- alter role authenticator reset pgrst.db_pre_request;
-- notify pgrst, 'reload config';
