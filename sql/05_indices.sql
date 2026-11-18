create index if not exists idx_inv_bodega_sku on public.bodega_inventario_ubicacion(bodega,sku);
create index if not exists idx_inv_bodega_lpn on public.bodega_inventario_ubicacion(bodega,lpn_origen);
create index if not exists idx_inv_bodega_ubicacion on public.bodega_inventario_ubicacion(bodega,ubicacion_id);
create index if not exists idx_ov_numero on public.netsuite_ordenes_venta(numero_ov);
create index if not exists idx_ov_estado_compuesto on public.netsuite_ordenes_venta(estado,estado_ns,bodega,id desc);
