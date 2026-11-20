@echo off
REM ==================================================================
REM  LUDIPEK WMS - Respaldo programado de todos los datos de Supabase
REM  Programarlo en Windows: Programador de tareas > Crear tarea básica >
REM  Diariamente (ej. 23:30) > Iniciar un programa > este archivo.
REM  El .zip queda en la carpeta "respaldos" del programa y el resultado
REM  en respaldos\ultimo_respaldo.log
REM  Con la llave pública en el .env, agregue también en el .env:
REM     WMS_RESPALDO_USUARIO=SU_USUARIO
REM     WMS_RESPALDO_CLAVE=SU_CLAVE
REM ==================================================================
cd /d "%~dp0.."
if not exist "respaldos" mkdir "respaldos"
if exist "dist\Ludipek_Torre_Control.exe" (
    "dist\Ludipek_Torre_Control.exe" --respaldo > "respaldos\ultimo_respaldo.log" 2>&1
) else if exist "Ludipek_Torre_Control.exe" (
    "Ludipek_Torre_Control.exe" --respaldo > "respaldos\ultimo_respaldo.log" 2>&1
) else (
    python main.py --respaldo > "respaldos\ultimo_respaldo.log" 2>&1
)
exit /b %ERRORLEVEL%
