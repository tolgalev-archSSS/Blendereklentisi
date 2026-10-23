# =====================================================================
# autostart_blender.py
# Blender, start_pipeline.bat tarafindan su sekilde cagrilir:
#   blender.exe --python autostart_blender.py
#
# Gorevler:
#   1. Proje icindeki blender_pipeline_addon klasorunu sys.path'e ekle
#      (Blender'in kendi addons klasorune kopyalamaya gerek yok).
#   2. Eklentiyi register() et -> DB init + HTTP sunucusu (8123) baslar.
#   3. Port hazir oldugunda tarayiciyi http://127.0.0.1:8123 adresine acar.
#
# ONEMLI: Arayuz YALNIZCA http://127.0.0.1:8123 uzerinden kullanilir.
# Eski "web_panel.html" / file:// sayfasi fetch hatalarina yol acar;
# bu betik onu ASLA acmaz.
# =====================================================================

import os
import sys
import time
import socket
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_PARENT = HERE  # blender_pipeline_addon buranin altinda
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

HOST, PORT = "127.0.0.1", 8123
URL = "http://%s:%d" % (HOST, PORT)


def _wait_port(timeout=15.0):
    """Sunucu portu gercekten dinlenene kadar bekler."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
        try:
            if s.connect_ex((HOST, PORT)) == 0:
                return True
        finally:
            s.close()
        time.sleep(0.3)
    return False


def _open_browser_when_ready():
    if _wait_port():
        webbrowser.open(URL)
        print("[AUTOSTART] Tarayici acildi: %s" % URL)
    else:
        print("[AUTOSTART] UYARI: %s portu acilamadi. Eski bir 'Model v2.5' "
              "eklentisi ayni portu kullanıyor olabilir; Blender > Preferences "
              "> Add-ons icinden kaldirin." % PORT)


def on_load():
    """Blender tamamen acildiktan sonra calisir (bpy.context hazirken)."""
    import bpy

    try:
        import blender_pipeline_addon as addon
        addon.register()
        print("[AUTOSTART] Eklenti kaydedildi ve sunucu baslatildi.")
    except Exception as e:  # noqa: BLE001
        print("[AUTOSTART] HATA: Eklenti yuklenemedi -> %s" % e)
        return

    threading.Thread(target=_open_browser_when_ready, daemon=True).start()


def main():
    import bpy

    print("=" * 50)
    print("  Asset Pipeline - Autostart (Faz 1)")
    print("=" * 50)

    # Cakisma kontrolu: port zaten doluysa eski bir oturum/eklenti var demektir.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.4)
    busy = s.connect_ex((HOST, PORT)) == 0
    s.close()
    if busy:
        print("[AUTOSTART] NOT: %s portu zaten kullanmda. Eski Blender oturumu "
              "kapatilmamis olabilir; yine de devam ediliyor." % PORT)

    # UI baglami hazir olur olmaz calistirmak icime timer
    bpy.app.timers.register(on_load, first_interval=1.0)


if __name__ == "__main__":
    main()
