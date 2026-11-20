@echo off
REM Abre el WMS apuntando a la base de PRUEBAS (lee .env.pruebas). Se ve una franja naranja.
cd /d "%~dp0.."
if not exist ".env.pruebas" (
    echo Falta el archivo .env.pruebas junto al programa. Vea GUIA_RESPALDO_Y_PRUEBAS.md
    pause
    exit /b 1
)
set WMS_AMBIENTE=PRUEBAS
if exist "dist\Ludipek_Torre_Control.exe" (
    start "" "dist\Ludipek_Torre_Control.exe" --pruebas
) else (
    python main.py --pruebas
)
