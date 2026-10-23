# ============================================================================
# autostart_blender.py
# Blender açılırken "blender.exe --python autostart_blender.py" ile tetiklenir.
#
# Görevleri:
#   1. Proje içindeki blender_pipeline_addon klasörünü sys.path'e ekler.
#   2. Eklentiyi register() eder (bpy.utils üzerinden).
#   3. Veritabanını hazırlar (init_db()).
#   4. Gömülü REST API sunucusunu localhost:8123 üzerinde başlatır.
#   5. Tarayıcıda http://127.0.0.1:8123 adresini otomatik açar.
# ============================================================================

import os
import time
import sys
import webbrowser

# --- Yol çözümü ---------------------------------------------------------------
# Bu dosya proje kökünde: <KOK>/autostart_blender.py
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_PARENT = SCRIPT_DIR  # blender_pipeline_addon bu klasörün altında
ADDON_PATH = os.path.join(SCRIPT_DIR, "blender_pipeline_addon")

if ADDON_PARENT not in sys.path:
    sys.path.insert(0, ADDON_PARENT)


def main():
    print("=" * 68)
    print("[AssetPipeline][Autostart] Blender otomatik başlatma betiği çalışıyor")
    print(f"[AssetPipeline][Autostart] Addon yolu : {ADDON_PATH}")

    if not os.path.isdir(ADDON_PATH):
        print("[AssetPipeline][HATA] blender_pipeline_addon klasörü bulunamadı!")
        print("  Beklenen konum:", ADDON_PATH)
        return

    try:
        import bpy
        HAS_BPY = True
    except ImportError:
        HAS_BPY = False
        print("[AssetPipeline][UYARI] bpy bulunamadı — Blender dışı test modu.")

    # --- 1) Eklentiyi içe aktar ve register et ---------------------------------
    if HAS_BPY:
        import blender_pipeline_addon as addon

        # N-panel / operatör sınıflarını kaydet (sunucu/timer hariç)
        try:
            addon.register()
            print("[AssetPipeline][Autostart] Eklenti sınıfları kaydedildi (N paneli hazır).")
        except ValueError:
            # Zaten kayıtlıysa sorun değil
            print("[AssetPipeline][Autostart] Eklenti zaten kayıtlı, atlanıyor.")

        # --- 2) Veritabanı ------------------------------------------------------
        from blender_pipeline_addon import db_manager

        db_manager.init_db()
        print(f"[AssetPipeline][Autostart] Veritabanı hazır: {db_manager.DB_PATH}")

        # --- 3) Sunucu + timer --------------------------------------------------
        # start_pipeline hem sunucuyu hem de ana-thread timer'ını başlatır
        result = addon.start_pipeline()
        print(f"[AssetPipeline][Autostart] {result.get('message')}")

        # --- 4) Tarayıcıyı aç ---------------------------------------------------
        def _open_browser():
            webbrowser.open("http://127.0.0.1:8123")
            print("[AssetPipeline][Autostart] Tarayıcıda http://127.0.0.1:8123 açıldı.")
            return None  # tekrar çalıştırma

        # Tarayıcıyı kısa bir gecikmeyle aç (sunucu soketi tamamen hazır olsun)
        bpy.app.timers.register(_open_browser, first_interval=1.5)
    else:
        # Blender dışı smoke-test modu: yalnızca DB + sunucu + tarayıcı.
        # (Addon __init__.py 'import bpy' içerdiğinden alt modüller doğrudan yüklenir.)
        if ADDON_PATH not in sys.path:
            sys.path.insert(0, ADDON_PATH)
        import db_manager
        import server

        db_manager.init_db()
        print(f"[AssetPipeline][Autostart] Veritabanı hazır: {db_manager.DB_PATH}")
        result = server.start_server()
        print(f"[AssetPipeline][Autostart] {result.get('message')}")
        webbrowser.open("http://127.0.0.1:8123")
        print("[AssetPipeline][Autostart] Tarayıcıda http://127.0.0.1:8123 açıldı.")
        # Test ortamında sunucunun birkaç saniye ayakta kalmasını sağla
        time.sleep(2)

    print("=" * 68)


if __name__ == "__main__":
    main()
