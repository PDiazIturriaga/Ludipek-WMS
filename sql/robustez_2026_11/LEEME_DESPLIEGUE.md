# LUDIPEK WMS · Robustez de base de datos (nov-2026)

Todo se ejecuta en **Supabase → SQL Editor**, un archivo a la vez y en orden.
Cada script es una transacción (si falla, no cambia nada) y se puede volver a ejecutar.

## Antes de empezar
1. Respaldo: Supabase → Database → Backups (o `pg_dump`).
2. Ejecutar `00_diagnostico.sql` y guardar el resultado (es solo lectura).

## FASE A — hoy (compatible con las apps actuales)
| Orden | Archivo | Qué hace |
|---|---|---|
| 1 | `01_limpieza_datos.sql` | SKU sin saltos de línea, vencimientos en un solo formato (corrige años `0028`), lotes `S/L` uniformes, ubicaciones `G05-01`→`G-05-01`, crea ZONA-PICKING/MERMA por bodega, elimina líneas triplicadas de traslados OT sin picking, repara `lotes_pickeados`. |
| 2 | `02_reglas_integridad.sql` | La base rechaza: SKU vacío, vencimientos inválidos, ubicaciones que no existen, bodegas desconocidas, cantidades negativas, pickeado > pedido. Kardex con hora del servidor. Permite al celular leer `asn_detalle` y guardar auditorías de vacías. |
| 3 | `03_auditoria_kardex.sql` | Tabla `wms_auditoria_inventario`: todo cambio de stock queda con antes/después, usuario y origen. Kardex no se puede editar ni borrar. Vista `v_wms_cuadratura_stock`. |
| 4 | `04_funciones_operacion.sql` | Funciones atómicas: `wms_cerrar_pallet_recepcion`, `wms_consultar_lpn`, `wms_almacenar_lpn`, `wms_mover_a_picking`, `wms_salida_picking`, `wms_registrar_conteo`, `wms_login`, `wms_cambiar_password`. |
| 4b | `01b_correccion_dia_00.sql` | **Ejecutar si ya corrió 01 antes del 18-11-2026 14:55.** Vencimientos GS1 con día `00` = último día del mes (01 los había dejado en día 01). |
| 4d | `04b_recepciones_sin_ubicar.sql` | Planilla de LPN recibidos que nunca se almacenaron, bloqueo de recepciones cerradas y cierre controlado por fecha de corte (paso 3 comentado). |
| 4c | `01c_resolver_lpn_repartidos.sql` | Plantilla para resolver LPN en dos ubicaciones **después del chequeo físico**. |
| 7 | `07_estados_picking_packing.sql` | **Obligatorio para el celular nuevo.** Cierre de picking (`wms_cerrar_picking`) y de packing (`wms_cerrar_packing`) en una sola transacción, con historial de estados y errores visibles. Agrega al catálogo PENDIENTE_FACTURACION, FACTURADO, DESPACHADO, ANULADO, CERRADO. Corrige bodegas mal escritas que bloqueaban el cambio de estado. |
| 8 | `08_estado_unico_ov.sql` | Las columnas `estado` y `estado_ns` de las órdenes quedan siempre iguales, y cualquier cambio de estado (también "Marcar facturada" del PC) queda en `wms_historial_estados`. |
| 9 | `09_tareas_conteo.sql` | Tareas de conteo (pasillo, vacías de un pasillo o SKU) asignadas desde el PC → el operador las ve en su celular con su avance. Convierte las asignaciones antiguas "RACK A" al formato nuevo. |
| — | `07b_diagnostico_ov.sql` | Solo lectura: radiografía de una orden (cabecera, líneas, kardex, packing, historial). Cambiar el número en la primera línea. |

Después de la Fase A: ejecutar de nuevo `00_diagnostico.sql`. Lo que quede son casos para conteo cíclico (filas duplicadas, LPN en dos ubicaciones).

## Instalar las apps nuevas
- **PC**: ya actualizado en la carpeta (usa `wms_login`, permisos como listas, OT sin triplicar, recepción CCP).
- **Celular**: compilar el `main.dart` nuevo e instalar el APK en **todos** los equipos.
  La app nueva usa las funciones del paso 4; la antigua deja de funcionar al aplicar la Fase B.

## FASE B — cuando TODOS los celulares tengan la app nueva
| Orden | Archivo | Qué hace |
|---|---|---|
| 5 | `05_endurecimiento_fase_b.sql` | La clave pública ya no puede escribir inventario ni recepciones (solo vía funciones), ni leer usuarios/contraseñas. Índice único de inventario (si no quedan duplicados). |
| 6 | `06_cifrar_passwords_fase_b.sql` | Cifra las contraseñas (bcrypt) — **irreversible**. Las nuevas se cifran solas. |

## Si algo sale mal
- `98_revertir_fase_b.sql` → vuelve a permitir escritura directa (apps antiguas).
- `97_revertir_fase_a.sql` → quita reglas, triggers y funciones (la limpieza de datos se revierte con el respaldo).

## Control diario sugerido
```sql
-- Movimientos de stock hechos FUERA de las funciones (no deberían existir tras la Fase B)
select * from wms_auditoria_inventario where origen = 'DIRECTO' order by ocurrido_en desc limit 50;
-- Picking sin stock registrado (programar conteo cíclico)
select * from historial_movimientos where tipo_movimiento like 'SALIDA_PICKING_SIN_STOCK%' order by fecha desc;
```
