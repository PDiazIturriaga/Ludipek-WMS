-- =====================================================================
-- LUDIPEK WMS · 06 CIFRAR CONTRASEÑAS  (FASE B · después de 05)
-- Convierte las contraseñas en texto plano a bcrypt. Es irreversible:
-- nadie (ni el administrador) podrá volver a leerlas; solo cambiarlas
-- desde el PC (Admin > Usuarios), que usa wms_cambiar_password().
-- Requiere que PC y celulares ya usen wms_login() (apps nuevas).
-- =====================================================================
begin;

update public.wms_usuarios
   set password = extensions.crypt(password, extensions.gen_salt('bf')),
       updated_at = now()
 where password !~ '^\$2[aby]\$';

-- Toda contraseña nueva o editada directo en la tabla se cifra sola
create or replace function public.wms_trg_cifrar_password()
returns trigger language plpgsql security definer set search_path = public, extensions as $$
begin
  if new.password is not null and new.password !~ '^\$2[aby]\$' then
    new.password := extensions.crypt(new.password, extensions.gen_salt('bf'));
  end if;
  return new;
end $$;

drop trigger if exists trg_cifrar_password on public.wms_usuarios;
create trigger trg_cifrar_password
  before insert or update of password on public.wms_usuarios
  for each row execute function public.wms_trg_cifrar_password();

commit;
