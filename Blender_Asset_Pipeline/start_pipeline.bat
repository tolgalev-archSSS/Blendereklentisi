@echo off
REM =====================================================================
REM start_pipeline.bat - Tek tikla baslatma (Windows)
REM  1. Gerekli klasorleri kontrol eder/olusturur
REM  2. Eski/cakisan sunucuyu temizler:
REM     - Port 8123 ve 9876/9877'yi kullanan BLENDER oturumlarini kapatir
REM       ("Model v2.5 / MLAO" eklentisi 9876-9877 portlarindan yayin yapiyordu;
REM        sadece Blender processleri kill'lenir, baska hicbir sey oldurulmez.)
REM  3. blender.exe'yi otomatik bulur (where -> Program Files taramasi)
REM  4. blender.exe --python autostart_blender.py ile baslatir
REM     (Tarayici http://127.0.0.1:8123 adresini kendiliginden acar.)
REM =====================================================================
setlocal EnableDelayedExpansion

title Asset Pipeline - Baslatma

echo ====================================================
echo   Asset Pipeline (Faz 1) - Baslatma Kontrolu
echo ====================================================

REM ---------- 1) Klasor kontrolleri ----------
if not exist "%~dp0database" mkdir "%~dp0database"
if not exist "%~dp0blender_pipeline_addon\ui" (
    echo [HATA] blender_pipeline_addon klasoru eksik!
    pause
    exit /b 1
)
echo [OK] Dosya yapisi tam.

REM ---------- 2) Cakisan eski oturumlari/sunuculari temizle ----------
echo [TEMIZLIK] Port 8123 / 9876 / 9877 dinleyen Blender islemleri kontrol ediliyor...

for %%P in (8123 9876 9877) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr /c:":%%P " ^| findstr /i "LISTENING"') do (
        tasklist /fi "PID eq %%A" /nh 2^>nul ^| findstr /i "blender" >nul 2>&1
        if !errorlevel!==0 (
            echo   - Port %%P uzerindeki Blender PID %%A kapatiliyor...
            taskkill /f /pid %%A >nul 2>&1
        )
    )
)

REM Ayni sekilde eski "Model v2.5" eklentisinin TCP sunucusu 9876'daydi;
REM yukaridaki dongu onu da kapsar. Pencere kapanip Blender yeniden acildiginda
REM SADECE bu proje yuklenecektir.
timeout /t 2 /nobreak >nul
echo [OK] Portlar temiz.

REM ---------- 3) blender.exe tespiti ----------
set "BLENDER_EXE="

where blender >nul 2>&1
if %errorlevel%==0 (
    for /f "delims=" %%I in ('where blender') do if not defined BLENDER_EXE set "BLENDER_EXE=%%I"
)

if not defined BLENDER_EXE (
    REM Program Files altinda en yeni Blender surumunu ara
    for /d %%D in ("C:\Program Files\Blender Foundation\Blender*") do (
        if exist "%%D\blender.exe" set "BLENDER_EXE=%%D\blender.exe"
    )
)
if not defined BLENDER_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Blender*") do (
        if exist "%%D\blender.exe" set "BLENDER_EXE=%%D\blender.exe"
    )
)

if not defined BLENDER_EXE (
    echo [HATA] blender.exe bulunamadi! Lutfen Blender'i kurun veya
    echo        asagidaki satirdaki yolu kendi Blender yolunuzla degistirin:
    echo        set "BLENDER_EXE=C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"
    pause
    exit /b 1
)
echo [OK] Blender: %BLENDER_EXE%

REM ---------- 4) Blender'i eklentiyle birlikte baslat ----------
echo [BASLAT] Blender aciliyor, eklenti ve sunucu yukleniyor...
start "" "%BLENDER_EXE%" --python "%~dp0autostart_blender.py"

echo.
echo ====================================================
echo   Blender aciliyor... Tarayici birazdan
echo   http://127.0.0.1:8123 adresini kendiliginden acar.
echo   (Eger acmazsa N Paneli ^> Asset Pipeline ^> Web Arayuzunu Ac)
echo ====================================================
echo   Bu pencere 10 saniye icinde otomatik kapanacak.
echo ====================================================
timeout /t 10 /nobreak >nul
endlocal
exit /b 0
