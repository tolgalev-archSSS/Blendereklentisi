@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

title Blender Asset Pipeline - Faz 1 Baslatici
color 0B

echo ====================================================================
echo   BLENDER ASSET PIPELINE  (Faz 1) - Otomatik Baslatma ve Kontrol
echo   11 Haneli Kodlama ^| SQLite ^| localhost:8123 REST API
echo ====================================================================
echo.

cd /d "%~dp0"

rem ---------------------------------------------------------------------
rem [1/4] Gerekli klasor/dosya kontrolleri
rem ---------------------------------------------------------------------
echo [1/4] Proje dosyalari kontrol ediliyor...

if not exist "database\" (
    echo       - "database" klasoru yok, olusturuluyor...
    mkdir "database"
)

if not exist "autostart_blender.py" (
    echo [HATA] autostart_blender.py bulunamadi! Bu .bat dosyasi proje
    echo        kok dizininde (Blender_Asset_Pipeline) olmali.
    pause
    exit /b 1
)

if not exist "blender_pipeline_addon\__init__.py" (
    echo [HATA] blender_pipeline_addon eklenti klasoru eksik veya bozuk!
    pause
    exit /b 1
)

echo       OK: database\ , autostart_blender.py , blender_pipeline_addon\
echo.

rem ---------------------------------------------------------------------
rem [2/4] Port 8123 kontrolu (sunucu zaten calisiyorsa uyar)
rem ---------------------------------------------------------------------
echo [2/4] Port 8123 kontrolu...
netstat -ano | findstr /r ":8123 .*LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo       UYARI: 8123 portunda zaten bir sunucu dinliyor.
    echo       Eski bir Blender oturumu acik olabilir. Web arayuzu yine de
    echo       mevcut sunucuya baglanacaktir.
) else (
    echo       OK: Port 8123 bos.
)
echo.

rem ---------------------------------------------------------------------
rem [3/4] blender.exe otomatik tespiti
rem ---------------------------------------------------------------------
echo [3/4] blender.exe araniyor...
set "BLENDER_EXE="

rem --- Yontem A: PATH uzerinde 'where' komutu ---
where blender >nul 2>&1
if %errorlevel%==0 (
    for /f "delims=" %%I in ('where blender') do (
        if not defined BLENDER_EXE set "BLENDER_EXE=%%I"
    )
)

rem --- Yontem B: Program Files altinda en yeni surumu tara ---
if not defined BLENDER_EXE (
    rem Klasor isimlerine gore ters siralama: once Blender 5.x, sonra 4.x, 3.x...
    for /f "delims=" %%D in ('dir /b /ad /o-n "C:\Program Files\Blender Foundation\Blender*" 2^>nul') do (
        if not defined BLENDER_EXE (
            if exist "C:\Program Files\Blender Foundation\%%D\blender.exe" (
                set "BLENDER_EXE=C:\Program Files\Blender Foundation\%%D\blender.exe"
            )
        )
    )
)

rem --- Yontem C: Yerel kullanici Steam/ozel kurulumlari (son care) ---
if not defined BLENDER_EXE (
    if exist "%LOCALAPPDATA%\Programs\Blender\blender.exe" (
        set "BLENDER_EXE=%LOCALAPPDATA%\Programs\Blender\blender.exe"
    )
)

if not defined BLENDER_EXE (
    echo [HATA] blender.exe otomatik bulunamadi!
    echo.
    echo        Lutfen Blender kurulum yolunuzu elle girin
    echo        (orn: C:\Program Files\Blender Foundation\Blender 4.2\blender.exe)
    echo        Bos birakirsaniz cikilir.
    echo.
    set /p "BLENDER_EXE=Blender yolu: "
)

if not defined BLENDER_EXE (
    echo [CIKIS] Blender bulunamadi, islem durduruldu.
    pause
    exit /b 1
)

if not exist "%BLENDER_EXE%" (
    echo [HATA] Girdiginiz yol gecersiz: %BLENDER_EXE%
    pause
    exit /b 1
)

echo       bulundu: %BLENDER_EXE%
echo.

rem ---------------------------------------------------------------------
rem [4/4] Blender'i autostart betigiyle baslat
rem ---------------------------------------------------------------------
echo [4/4] Blender baslatiliyor (eklenti + sunucu + web arayuzu otomatik)...
echo       Adres: http://127.0.0.1:8123
echo.

start "" "%BLENDER_EXE%" --python "%~dp0autostart_blender.py"

echo Blender penceresi acildi. Kisa sure icinde tarayicida
echo http://127.0.0.1:8123 adresi otomatik olarak acilacaktir.
echo.
echo Bu pencereyi kapatabilirsiniz; Blender arka planda calismaya devam eder.
timeout /t 8 >nul
exit /b 0
