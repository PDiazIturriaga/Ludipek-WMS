# ======================================================================
#  LUDIPEK WMS - Copiar la ESTRUCTURA de producción al proyecto de PRUEBAS
#  (tablas, funciones, políticas y permisos) + datos de referencia
#  (maestra, ubicaciones, usuarios, configuración). NO copia stock ni movimientos.
#
#  Requisitos: herramientas cliente de PostgreSQL 17 (pg_dump y psql) instaladas:
#    https://www.postgresql.org/download/windows/  (instalar solo "Command Line Tools")
#  Las cadenas de conexión están en Supabase > Connect > "Session pooler" (puerto 5432).
#  Se piden al ejecutar y NO se guardan en ningún archivo.
#
#  Uso (PowerShell, en la carpeta del programa):
#    powershell -ExecutionPolicy Bypass -File herramientas\clonar_esquema_a_pruebas.ps1
# ======================================================================
$ErrorActionPreference = "Stop"
foreach ($exe in @("pg_dump", "psql")) {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        Write-Host "No se encontró $exe. Instale las herramientas de PostgreSQL 17 y agregue su carpeta bin al PATH." -ForegroundColor Red
        exit 1
    }
}
Write-Host "Cadena de conexión de PRODUCCIÓN (solo lectura, se usa para copiar):" -ForegroundColor Cyan
$prod = Read-Host "postgresql://postgres.xxxx:CLAVE@aws-...pooler.supabase.com:5432/postgres"
Write-Host "Cadena de conexión de PRUEBAS (aquí se escribe):" -ForegroundColor Yellow
$prue = Read-Host "postgresql://postgres.yyyy:CLAVE@aws-...pooler.supabase.com:5432/postgres"
if ($prod -eq $prue) { Write-Host "Las dos cadenas son iguales. Cancelado." -ForegroundColor Red; exit 1 }
$conf = Read-Host "Se va a ESCRIBIR en el proyecto de PRUEBAS. Escriba PRUEBAS para continuar"
if ($conf -ne "PRUEBAS") { Write-Host "Cancelado."; exit 1 }

$tmp = Join-Path $env:TEMP "wms_clon"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$esquema = Join-Path $tmp "esquema.sql"
$datos = Join-Path $tmp "datos_referencia.sql"

Write-Host "1/4 Copiando estructura de producción..."
& pg_dump $prod --schema=public --schema=wms_interno --schema-only --no-owner --quote-all-identifiers -f $esquema
Write-Host "2/4 Copiando datos de referencia..."
$tablas = @("wms_config", "wms_modulos_app", "wms_usuarios", "maestra_sku", "bodega_ubicaciones",
            "wms_ubicacion_picking_sku", "wms_zonas_comunas", "wms_flota_vehiculos", "wms_correlativos")
$parametros = @($prod, "--data-only", "--no-owner", "--disable-triggers", "-f", $datos)
foreach ($t in $tablas) { $parametros += @("--table=public.$t") }
& pg_dump @parametros

Write-Host "3/4 Creando estructura en PRUEBAS (los avisos 'already exists' son normales)..."
& psql $prue -v ON_ERROR_STOP=0 -q -f $esquema 2>&1 | Out-File (Join-Path $tmp "log_esquema.txt")
Write-Host "4/4 Cargando datos de referencia y activando el portero..."
& psql $prue -v ON_ERROR_STOP=0 -q -f $datos 2>&1 | Out-File (Join-Path $tmp "log_datos.txt")
& psql $prue -q -c "alter role authenticator set pgrst.db_pre_request to 'public.wms_pre_request'; notify pgrst, 'reload config'; notify pgrst, 'reload schema';"

$err = (Select-String -Path (Join-Path $tmp "log_*.txt") -Pattern "ERROR" | Where-Object { $_ -notmatch "already exists" }).Count
Write-Host ""
Write-Host "Listo. Errores a revisar: $err  (detalle en $tmp\log_esquema.txt y log_datos.txt)" -ForegroundColor Green
Write-Host "Recuerde en el proyecto de pruebas: Authentication > Sign In > activar 'Allow anonymous sign-ins'."
Remove-Item $esquema, $datos -ErrorAction SilentlyContinue
