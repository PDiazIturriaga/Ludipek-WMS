-- Ejecutar solo después de confirmar que las aplicaciones usan anon/authenticated.
grant usage on schema public to anon, authenticated;
grant select,insert,update on public.wms_packing_cabecera, public.wms_packing_pallet, public.wms_packing_linea,
 public.asn_packing_list_detalle, public.wms_historial_estados, public.wms_catalogo_estados to anon,authenticated;
grant usage,select on all sequences in schema public to anon,authenticated;
alter table public.wms_packing_cabecera enable row level security;
alter table public.wms_packing_pallet enable row level security;
alter table public.wms_packing_linea enable row level security;
alter table public.asn_packing_list_detalle enable row level security;
do $$
declare t text;
begin
 foreach t in array array['wms_packing_cabecera','wms_packing_pallet','wms_packing_linea','asn_packing_list_detalle'] loop
  execute format('drop policy if exists %I on public.%I',t||'_rw',t);
  execute format('create policy %I on public.%I for all to anon,authenticated using (true) with check (true)',t||'_rw',t);
 end loop;
end $$;
